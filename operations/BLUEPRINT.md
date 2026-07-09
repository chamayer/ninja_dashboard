# Parity Blueprint — Operations replaces the legacy AC engine

Implements DESIGN.md §8–§12: full functional parity with
`ingest/agent_compliance` + the standalone compliance/inventory scripts +
the operational intent of the Metabase dashboards, then deletion of
`ninja_agent_compliance`. Every spec below is derived from legacy code
(file:line cited). No guessing.

**Hard rule (DESIGN §8):** no new code imports `ingest.agent_compliance.*`
or queries `ninja_agent_compliance.*`. Track 0 removes the three existing
violations (`source_observations.py:24-25`, `source_run_queue.py:140`,
`identity/resolver.py:20`).

**Engine-first rule (DESIGN §11.4):** no UI surface ships before its
engine produces real data.

Backlog (explicitly NOT in scope): CVE/NVD enrichment (3b),
VirusTotal/MalwareTips reputation, user-risk scoring, DB role rename.

---

## Track 0 — Legacy severance

### 0.1 Move connectors and normalize to neutral homes

| From | To |
|---|---|
| `ingest/agent_compliance/clients/ninja.py` | `ingest/connectors/ninja_presence.py` |
| `ingest/agent_compliance/clients/sentinelone.py` | `ingest/connectors/sentinelone.py` |
| `ingest/agent_compliance/clients/screenconnect.py` | `ingest/connectors/screenconnect.py` |
| `ingest/agent_compliance/clients/logmein.py` | `ingest/connectors/logmein.py` |
| `ingest/agent_compliance/normalize.py` | `ingest/normalize.py` |

Git `mv` + import rewrite. Connectors currently import `SourceConfig`
from `config_loader` and helpers from `normalize` — after the move they
import from `ingest.sources` (0.2) and `ingest.normalize`. Update
importers: `source_observations.py`, `source_run_queue.py`,
`identity/resolver.py`, `identity/fast_path.py` (if applicable).

`ingest/normalize.py` keeps ALL legacy helpers verbatim
(normalize.py:1-91): `normalize_hostname`, `normalize_loose_hostname`,
`is_macos_name`, `normalize_org_name`, `is_placeholder_org_name`,
`canonical_platform`, `parse_dt`, `infer_device_type`.

### 0.2 Operations-native source configuration

New `ingest/sources.py` with the `SourceConfig` dataclass (same fields
as `config_loader.py:19-42` minus legacy `client_id`/`client_name` ints)
and `load_sources()` reading:

```sql
SELECT s.id, s.name, s.kind, si.id, si.client_id, si.config, si.enabled,
       sb.id AS source_binding_id, ci.id AS collector_instance_id
FROM operations.sources s
JOIN operations.source_instances si ON si.source_id = s.id
JOIN operations.source_bindings sb ON sb.source_instance_id = si.id
JOIN operations.collector_instances ci ON ci.id = sb.collector_instance_id
WHERE si.enabled AND sb.enabled
```

`source_instances.config` JSONB (field exists, models.py:308) carries:
`platform`, `source_key`, `is_shared`, `base_url`, `token_url`, and the
secret env-var refs (`api_token_ref`, `client_id_ref`,
`client_secret_ref`, `ext_guid_ref`, `secret_key_ref`, `company_id_ref`,
`psk_ref`). Secrets resolve via `os.environ.get(ref)` exactly as
`config_loader.py:57-60`. entity_type derives from `sources.kind` with
the same CASE mapping (`config_loader.py` load_sources): rmm→agent.rmm,
edr→agent.edr, remote_access→agent.remote_access.

**Migration 0018 (RunPython):** copy every row of
`ninja_agent_compliance.platform_sources` into `source_instances.config`
on the matching Source (create SourceInstance/SourceBinding where the
0015 seeds don't already cover it). Secret ref *names* copy as-is —
values stay in the server `.env`. This migration reads the legacy schema
(allowed: migrations are cutover machinery, not runtime dependency).

### 0.3 Client resolution without legacy aliases

`operations.client_links` is the single source of group→client mapping
(replaces `client_platform_links` + `client_aliases`,
`config_loader.py:158-316`).

- **Migration 0018 (same file):** seed `client_links` from
  `ninja_agent_compliance.client_platform_links` joined to the
  operations client (match on client name → `operations.clients`).
- `source_observations.py`: resolve `client_id` for an observation by
  `(source_id, platform_group_id)` lookup in `client_links` FIRST, then
  fall back to the current device-based resolution
  (`source_observations.py:161-169`).
- Unmatched groups: insert into a new `operations.unmatched_source_groups`
  table (tenant, source, external_id, external_name, first_seen, count) —
  the Review workflow surface for org mapping (replaces `org_candidates`,
  `config_loader.py:319-648`). Skip placeholder names via
  `is_placeholder_org_name` (normalize.py:65-68).

### 0.4 Delete the AC scheduler entry

`main.py:39-47` imports and schedules `agent_compliance_ingest` +
`review_digest`. Leave running until Track 6 cutover, but all NEW
scheduling (evaluator, dispatcher, source runs) must hang off the
operations-native jobs (`main.py:127-160` pattern), never the AC run.

**Verify:** `rg "agent_compliance" ingest/source_observations.py
ingest/source_run_queue.py ingest/identity/ ingest/connectors/` → zero.
S1/SC/LMI observation counts unchanged after redeploy (compare
`entity_observations` per platform before/after).

---

## Track 1 — Evaluator parity

All changes in `ingest/evaluator.py` unless noted. Legacy reference:
`ingest/agent_compliance/ingest.py:442-605` (matrix builder),
`:816-861` (priority/staleness helpers), `:887-931` (finding emission).

### 1.1 Device promotion — observation-driven universe

New resolver step (`ingest/identity/resolver.py`): after matching
attempts fail, promote stable unmatched clusters into canonical devices.

- Cluster = unresolved observations grouped by
  `(client_id, normalize_hostname(canonical_data->>'hostname'))`.
- Promote when: cluster has observations spanning ≥ 24h AND no pending
  `identity_candidate` involving the hostname.
- Action: INSERT `operations.devices` (canonical_hostname, client,
  device_type inferred, `created_reason='<platform>.ingest.new_device'`)
  + `device_links` row + backfill `device_id` on the cluster's
  observations.
- A device that later matches a Ninja device becomes a merge candidate
  (Track 4 cascade handles it).

### 1.2 device_scope filtering

`_evaluate_coverage` currently fetches `device_scope` and ignores it
(evaluator.py:72). Fix: add
`AND (%s = 'all' OR d.device_type = %s)` to the device query, with
scope mapped servers→'server', workstations→'workstation'.
Prerequisite: `ingest/core/devices.py` populates
`operations.devices.device_type` from Ninja node_class via
`infer_device_type` (normalize.py:83-91); promotion (1.1) infers from
os_name.

### 1.3 Exemptions

Legacy: `no_av_exempt` flag from Ninja custom field removes S1 from
required platforms (ingest.py:474-528 exemption branch). New:

- Migration 0019: `operations.devices.exemptions JSONB NOT NULL DEFAULT '{}'`.
- `ingest/core/devices.py`: set `exemptions = {'agent.edr': 'no_av_exempt'}`
  when the Ninja device carries the NO AV marker (same detection as
  legacy Ninja client).
- Evaluator: skip requirement when
  `devices.exemptions ? requirement.entity_type`.

### 1.4 stale_required_platform findings

New branch in `_evaluate_coverage`: platform observed but
`last_observed_at` older than `gap_after_hours` → finding type
`stale_required_platform` (instead of missing). Mirrors legacy stale
set (ingest.py:476-528, `_is_stale` :849-854). Seed the finding type
(migration 0019 RunPython): entity class, source_module
`platform.evaluator`, default severity medium, auto_resolvable.

### 1.5 Source-failure guard + admin finding

- `source_observations.py` / `source_run_queue.py` already isolate
  per-source failures — additionally record every run outcome in
  `operations.run_log` (RunLog model exists; domain =
  `source.<platform>.<source_key>`).
- Evaluator preamble: for each platform required by any requirement,
  check latest run_log entry for its sources. If latest run failed or
  is older than 2× schedule interval → open `source_failure` **admin**
  finding (condition_key = source_key) and add platform to a
  `skip_platforms` set; requirements targeting it are not evaluated
  this cycle. Auto-resolve the admin finding on next successful run.
- Seed finding type `source_failure` (admin, `platform.evaluator`,
  high, auto_resolvable) in migration 0019.

### 1.6 Corroborated confidence (DESIGN §6.5)

`confirmed` requires: thresholds crossed AND device seen online by ≥1
platform within that platform's staleness window — check
`agent_presence_current` joined to latest observation
`canonical_data->>'is_online' = 'true'`. Otherwise cap at `probable`.
Port of legacy `confirmed_gap` (ingest.py:887-908).

### 1.7 cross_client_conflict findings

Same `normalize_hostname` resolving to devices under different clients
(legacy ingest.py:516, :608-620). Emit finding type
`cross_client_conflict` (entity, severity medium, subject = each
device) with the peer device/client in finding_details. Seed type in
migration 0019.

### 1.8 device_long_offline / device_stale_data

Finding types already seeded (migration 0013). Add emission:
`device_long_offline` when Ninja reports `is_online=false` continuously
> 7d (from agent.rmm observations); `device_stale_data` when a device's
newest observation across ALL platforms > 7d old. Auto-resolve both.

**Verify (per phase):** SQL counts of findings by type vs. legacy
`compliance_findings` for the same fleet; spot-check 5 devices per
type.

---

## Track 2 — Notification dispatcher

New file `ingest/notifications.py`. Legacy reference: `alerts.py` in
full (read 2026-07-09; line refs below).

### 2.1 Dispatcher loop

`dispatch(tenant_id) -> int`, scheduled after each evaluator run + a
periodic sweep:

1. Load candidate findings: `operations.findings` + `admin_findings`
   with `status IN ('open','acknowledged')`.
2. **Suppression filter** — port of alerts.py:38-47: exclude findings
   matching an enabled `suppression_rules` row (subject_match JSONB
   matches on client/device/finding_type/platform; NULL = wildcard;
   `expires_at` respected).
3. **Rule match** — port of alerts.py:86-111: most-specific-first
   `ORDER BY client_id NULLS LAST, (match_criteria->>'platform') NULLS
   LAST, (match_criteria->>'device_scope') NULLS LAST LIMIT 1` against
   `notification_rules` (enabled, finding_type, finding_class,
   min_severity ladder, min_confidence ladder — confirmed > probable >
   possible).
4. **Cooldown/dedup** — `notification_state` keyed
   (fingerprint=condition_key, rule): skip if `next_allowed_at > now`.
   On send: upsert `last_sent_at`, `next_allowed_at = now +
   cooldown_hours`, `send_count += 1` (replaces alert_state,
   alerts.py:155-204).
5. **Urgency re-escalation** — findings `acknowledged` with
   `last_detected_at` still advancing and `now - last_sent_at >
   rule.urgency_hours` → send again regardless of cooldown (new
   capability, DESIGN §6.5).
6. **Send** — channel from `NotificationRoute`: webhook / email /
   zendesk. Port senders verbatim from alerts.py:238-311 (httpx POST
   with env-ref URL; SMTP with STARTTLS/auth; Zendesk /api/v2/requests
   with requester + text body). Payload shape from alerts.py:207-219
   adapted to finding fields; `_text_body` port (alerts.py:314-327).
7. **Audit** — insert `notification_events` (rule, fingerprint,
   channel, status sent/failed/suppressed, payload_ref, error).

Settings: reuse the `AGENT_COMPLIANCE_*` env names for SMTP/Zendesk in
v1 (values already on the server), read via a new `ingest/config.py`
settings group named `NOTIFY_*` with fallback to old names. Old names
removed at Track 6.

### 2.2 Migration 0020

- Add `'zendesk'` to NotificationRoute channel choices.
- RunPython: create default `notification_rules` from legacy
  `alert_rules` (rule per finding_type/platform/client with cooldown,
  route mapped to migrated routes from 0017). Rules created disabled;
  operator enables after review.

### 2.3 Review digest

`ingest/notifications_digest.py`: daily job aggregating findings with
`confidence < confirmed` (the review class, review_digest.py:27-60):
totals, by_client, by_type, 100-row sample → send to the route flagged
`mode='digest'`.

### 2.4 Configure UI (Track U grammar)

Pages: notification rules list/edit, routes list/edit (channel +
target_ref only), suppressions list with **ignore/restore** (create
suppression from a finding row; restore = disable). All writes audited
via AuditLog.

**Verify:** synthetic finding → rule → webhook catcher on am-ch-01
receives payload; second run within cooldown sends nothing;
`notification_events` rows for both attempts.

---

## Track 3 — Software findings (3a only; 3b CVE → backlog)

Legacy reference: `analyze_inventory (75).py` classification stages +
the 8 finding types seeded in migration 0007/0013.

### 3.1 Classifier engine

New `ingest/software_findings.py`, `classify(tenant_id) -> int`,
scheduled after each software refresh. Input:
`software_installations_current` (current, non-stale rows). Rules,
in decision order (decisions override, then):

| Finding type | Rule (port of analyze_inventory heuristics) |
|---|---|
| `suspicious_name` | name matches regex set: keygen, crack, loader, hack, exploit, miner, rat, keylog, toolbar, `setup\d{6,}` |
| `install_path_suspicious` | location matches: temp dirs, appdata\local\temp, downloads, desktop, recycle, hex-only dirs |
| `unauthorized_av` / `unauthorized_rmm` / `unauthorized_remote_access` | catalog category = av/rmm/remote_access AND product not in the client's sanctioned set (sanctioned = the platforms in coverage_requirements + explicit approvals) |
| `multi_av_conflict` | ≥2 distinct catalog-category=av products on one device |
| `rare_recent` | canonical_name on ≤2 devices fleet-wide AND first_seen < 30d |
| `eol_runtime` | name+version matches static EOL list (seed from the Metabase card's list, `inventory/metabase_bootstrap.py`) |

Findings: subject=device, condition_key =
sha256(tenant:client:device:type:canonical_name), confidence=confirmed
(deterministic rules), auto-resolve when the installation row goes
stale/absent or a decision approves it.

### 3.2 Catalog + decisions

- `SoftwareCatalog` (model exists): seed category keyword lists
  (av/rmm/remote_access product names — port from
  `inventory/metabase_bootstrap.py` and
  `agent_compliance/metabase_bootstrap.py` SQL card lists) +
  trusted-publisher list (~30 entries) + whitelist (~25) from
  analyze_inventory. Migration 0021 RunPython.
- `SoftwareDecision` (model exists): decisions =
  approve / approve_publisher / reject / investigate, global or
  per-client. Approve ⇒ classifier skips + auto-resolves open findings
  for that software(+publisher) scope. Reject ⇒ force finding severity
  high.

### 3.3 Review UI

Software decisions queue (Review grammar): needs-review list ranked by
spread (device_count) and category; row actions approve /
approve-publisher / reject / investigate; decisions audit-logged.
Client software page gains status badges (known good / needs review /
flagged) from catalog+decisions.

**Verify:** classifier run on live data; counts per finding type sane
(spot-check 10); approving a title resolves its findings on next run.

---

## Track 4 — Identity fidelity

Legacy reference: normalize.py (ported in Track 0), matching passes in
ingest.py:623-797, PS1 prefix logic (Multi_org_agent_compliance.ps1:294-306).

### 4.1 Matching upgrades (fast_path + resolver)

- Strict `normalize_hostname` on both sides of every hostname
  comparison (store `canonical_hostname` normalized at write).
- **Loose/macOS pass**: if strict fails and either side
  `is_macos_name`, compare `normalize_loose_hostname` (ingest.py:645-698
  safe-match: only when unique across the client).
- **Prefix pass**: unique prefix match ≥10 chars within the same client
  (ingest.py:760-797; PS1:294-306). Unique → resolve; multiple →
  identity_candidate.
- **Serial quality** (DESIGN §4.1): `is_placeholder_serial()` +
  fleet-wide duplicate check; low-quality serials never match. Store
  quality reason in device_links or compute in a view for the UI.

### 4.2 Candidate confirm/reject + cascade

Views + POST endpoints on identity_candidates (Review grammar):

- **Confirm** = merge: choose survivor (Ninja-linked wins, else older);
  re-point `device_links`, `entity_observations.device_id`, open
  `findings.subject_id`; tombstone loser
  (`deleted_at`, `deleted_reason='operator.merged'`); resolve the
  candidate; cascade re-run `drain_resolution` for the hostname.
- **Reject**: status=rejected; pair excluded from future candidate
  creation (unique constraint already exists).
- All actions audit-logged.

### 4.3 Conflict surfaces

Identity review page (Admin): pending candidates, cross-client
conflicts (Track 1.7 findings), serial-quality table, unresolved
observations count by platform, unmatched source groups (Track 0.3).
Replaces the Metabase "Inventory — Identity Review" intent.

**Verify:** candidate counts drop after confirm; merged device shows
both source links on its device page; zero orphaned observations
(`device_id` pointing at tombstoned device).

---

## Track 5 — Patching platform layer (DESIGN §10)

Design approved in DESIGN §10. Reads `ninja_patches.current_patch_state`,
`latest_install_outcome`, `device_patch_signal` (staging stays — §2).

### 5.1 Evaluator extension

`ingest/evaluator.py` (or `ingest/patch_findings.py`) emits per DESIGN
§10 table: `device_never_patched`, `patching_stalled` (35d),
`reboot_pending` (>3d), `patch_failing_repeatedly` (≥3 consecutive
fails per KB), `patch_approval_backlog` (subject=client). Device
subjects resolve ninja device id → operations device via device_links.
Seed the 5 finding types (migration 0022). Auto-resolve on condition
clear. Thresholds as coverage-style config later if needed — constants
first.

### 5.2 Surfaces

- **Patching** nav domain: work queue (triage tiles: never patched /
  stalled / reboot pending / failing / approval backlog → filterable
  table → device page), client patch review (client context).
- Device page patch tab: current patch state + recent outcomes.
- Trends/evidence remain Metabase (unaffected — they read
  `ninja_patches`).

**Verify:** counts match the Metabase Command Center scalars for the
same instant.

---

## Track U — UI framework (build first, surfaces land per-track)

Per DESIGN §11. One slice, before Tracks 1-5 surfaces:

- `base.html` nav: `Dashboard · Compliance · Software · Patching ·
  Findings · Admin` + client-context subnav.
- Shared includes: `_tiles.html`, `_filterbar.html`, `_table.html`,
  `_pagination.html`, `_badges.html` (severity/status/confidence),
  `_freshness.html` (run_log lookup by domain).
- Canonical device page consolidating: identity links, agent presence
  (from `agent_presence_current`), software, patches (Track 5), open
  findings. Client page gains the same sections in rollup form.
- Refactor the three existing list pages (devices, software, findings)
  onto the shared components — proves the grammar before new pages.

---

## Track 6 — Cutover

1. **Side-by-side validation**: script `ingest/parity_check.py` — for N
   days, after each cycle, compare legacy `compliance_findings` vs
   `operations.findings` (counts per type × client; list asymmetric
   diffs). Report into run_log + a Health page card.
2. Enable notification_rules (created disabled in 2.2); disable legacy
   `AGENT_COMPLIANCE_ALERTS_ENABLED`. One cycle overlap max — no double
   alerting.
3. Remove AC scheduler entries from `main.py`; delete
   `ingest/agent_compliance/`; delete `review_digest` legacy path.
4. Metabase disposition per DESIGN §12 — inventory of cards rebuilt vs
   deleted, approved explicitly before step 5.
5. Migration: `DROP SCHEMA ninja_agent_compliance CASCADE` — only after
   `rg "ninja_agent_compliance"` (excluding migrations) → zero and 1
   week of clean parity reports.

---

## Deployment batches

Each batch = one push + Portainer redeploy + verify. Order within a
batch is a single commit series; batches are sequential.

| Batch | Content | Gate to next |
|---|---|---|
| P0 | Track 0 (severance) + migration 0018 | S1/SC/LMI observation counts unchanged; zero legacy imports in new pipeline |
| P1 | Track 1 (evaluator parity) + migration 0019 | Finding counts vs legacy within tolerance |
| P2 | Track 2 (dispatcher) + migration 0020 — rules disabled | Webhook test delivery + cooldown verified |
| P3 | Track U (UI framework + canonical device page) | Browser check on refactored pages |
| P4 | Track 3 (software findings) + migration 0021 + review UI | Classifier counts sane; decision round-trip works |
| P5 | Track 4 (identity fidelity + review UI) | Candidate confirm cascade verified |
| P6 | Track 5 (patching) + migration 0022 + surfaces | Counts match Metabase scalars |
| P7 | Track 6 (cutover) — multi-step, each step separately approved | Parity clean 1 week → schema drop |

---

## Pre-push checklist (every batch)

- [ ] `python manage.py check` zero errors; `ruff` clean on changed files
- [ ] New migrations reviewed; RLS + grants on any new tenant-scoped table
- [ ] Dockerfile COPYs every new path (`ingest/connectors/`, new templates)
- [ ] No `ninja_agent_compliance` / `ingest.agent_compliance` reference in NEW code (grep)
- [ ] After renames/moves: grep OLD module paths — zero hits is the only pass
- [ ] Report short commit hash after push
