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

## Track E — Entity model correction (PRIORITY — before P2)

**STATUS: COMPLETE 2026-07-12.** E1 gate exact; E2 deployed (0024/0025,
client-scoped identity, lifecycle transitions, all-stream presence with
platform last-contact); E2b clean rebuild verified from zero; E3 entrypoint
bootstrap retired. See SESSIONS.md 2026-07-12 for verification numbers and
residuals. P2 unblocked.

Added 2026-07-10 after live data showed inflated inventory and broken
coverage. Three user-set principles govern this track:

1. **Ninja is an aggregation agent, not one source.** Its records are
   distinct observation streams distinguished by `node_class`: an RMM
   agent install, a hypervisor's guest inventory claim, a network
   device seen by NMS. A `vm.guest` record proves the VM exists — NOT
   that an agent is on it.
2. **Same-name records are LINKED entities, not duplicates.** One
   canonical device = (client, normalized hostname); every source
   record (including multiple from the same source, e.g. agent record
   + Hyper-V guest record) is its own `device_links` row with its
   observations intact. Nothing merged away, nothing deleted.
3. **Everything visible.** Anything that shows up in any source is
   inventory. Gaps are questions surfaced as findings (why no agent /
   offline / needs cleanup) — never hidden rows.
4. **No unnecessary forced waits.** Promotion on first observation,
   evaluation triggered by ingest completion, identity resolution
   inline with the write path. Scheduled sweeps are backstops, never
   the primary path. No maturation windows or artificial spans.

### E.1 node_class → entity_type mapping (data audit first)

Run `SELECT node_class, COUNT(*) FROM ninja_core.devices GROUP BY 1`
and pin the mapping. Expected:

| node_class pattern | entity_type | semantics |
|---|---|---|
| WINDOWS_*, MAC*, LINUX_* (agented) | `agent.rmm` | Ninja agent installed |
| *_VMM_GUEST / *_VM_GUEST | `vm.guest` | hypervisor says VM exists |
| *_VMM_HOST / *_HOST | `vm.host` | hypervisor host |
| NMS_* | `network.device` | seen by network monitoring |
| anything unmapped | `unknown` + admin finding | never silently dropped |

### E.2 Ninja observation writer

Extend the Ninja ingest (`ingest/core/devices.py`
`_sync_operations_device_links`) to emit `entity_observations` for
EVERY ninja_core.devices row, classified per E.1 — today it only
writes `agent.rmm` for already-linked devices. `canonical_data`
carries hostname, serial, vm uuid, node_class, last_contact (platform
truth), is_online. Dual-write alongside bootstrap until E.4.

### E.3 Uniform identity layer (resolver/fast_path)

- Match precedence: serial (quality-checked) > vm_uuid > strict
  normalized hostname, always within client scope first.
- **Explainable identity:** migration adds `device_links.match_method`
  (serial / vm_uuid / hostname_strict / hostname_loose / manual /
  promoted / bootstrap) + `match_confidence`. Every link auditable and
  operator-reversible.
- **Lifecycle state machine:** `devices.lifecycle_status`
  (active / offline_aging / pending_cleanup / retired), transitions
  driven by platform last-contact + operator decisions. Retired stays
  fully queryable with history — visible, just out of coverage
  denominators. "Everything visible" without "everything noisy".
- Same-client, same-hostname existing device → attach as an
  ADDITIONAL device_link (multi-links per source are legal; unique key
  is (tenant, source, external_id)). Canonical fields: the freshest
  record by platform last-contact wins, `agent.rmm` records preferred
  over `vm.guest` for device_type/os fields. Conflicting serials among
  linked records → finding, not a blocker.
- Cross-client same-hostname → identity_candidate (review), as today.
- **Promotion = always and immediate** for any unmatched cluster from
  ANY stream (everything visible). Promoted entity carries its
  entity_type context so the evaluator can ask the right question:
  `vm.guest`-only → missing agent.rmm; `agent.remote_access`-only →
  probably retired hardware, cleanup finding.

### E.4 Retire the Ninja bootstrap privilege

`bootstrap_devices_from_ninja` (entrypoint.sh) stops creating devices;
Ninja device creation flows through E.2 + E.3 like every other source.
Keep a link-integrity sync only if the observation path proves
insufficient. Remove entrypoint call last, after one clean cycle.

### E.5 Clean rebuild (user-approved 2026-07-10 — replaces repair SQL)

Derived data is nuked and re-ingested; operator-authored data is kept.

- **Truncate:** devices, device_links, entity_observations,
  findings, admin_findings, identity_candidates, notification_state,
  notification_events; refresh `agent_presence_current` (empty).
- **Keep:** clients, client_links, coverage_requirements,
  notification rules/routes, suppression_rules, software decisions,
  audit logs, users/sessions.
- **Sequence:** correct writers deploy FIRST (E1–E2), then truncate,
  then full re-ingest from ninja_core + source APIs, then verify from
  zero. Accepted trade-off: observation history/first-seen resets
  (old lineage was recorded against a broken identity model).

### E.6 Coverage semantics per entity type

- Coverage requirements evaluate against entity types, not "sources":
  RMM coverage = `agent.rmm` present; a `vm.guest` observation never
  satisfies it.
- `device_long_offline` / staleness switch to platform last-contact
  (`canonical_data->>'last_seen_at'`), not our fetch time.
- Device page lists every link with its entity_type + per-record
  last-contact; client cards count by entity_type (matview already
  keyed on it).

### E.7 device_type refactor — form factor only

`Device.DeviceType` currently encodes agent presence (`vm-with-agent` /
`vm-agentless`) — an observation-derived, time-varying fact baked into a
canonical attribute, and bootstrap's `_classify` guesses it ("treat as
agented VM"). Repair: device_type becomes pure form factor
(physical / vm / hypervisor-host / network-device / unknown); agent
presence comes ONLY from `agent_presence_current`. Migration remaps
existing values; grep-audit every `device_type` consumer (evaluator,
views, templates).

### E.8 No hidden exclusions

`_evaluate_coverage` excludes `_NON_AGENT_DEVICE_TYPES` from evaluation
entirely — devices silently outside the universe. Repair: drop the
blanket exclusion; applicability is expressed per requirement
(entity_type + device_scope), and inapplicable simply means no finding —
the device itself is always visible and countable. Same principle for
the resolver's `pending_hostnames` skip: entities awaiting identity
review must still be visible (as candidates), not absent.

### Contradictions audit (2026-07-10, code-verified)

| # | Violation | Where | Repair |
|---|---|---|---|
| 1 | Privileged device creation, no observations | `bootstrap_devices_from_ninja` + entrypoint | E.4 |
| 2 | Only already-linked Ninja rows produce observations; unlinked rows invisible | `ingest/core/devices.py:310-313` (`if not entry: continue`) | E.2 |
| 3 | Every Ninja row labeled `agent.rmm` — guest/NMS records become false agent presence | `ingest/core/devices.py:346` | E.1+E.2 |
| 4 | device_type encodes agent presence + guessed | `models.py:213-219`, bootstrap `_classify` | E.7 |
| 5 | Coverage universe silently excludes device types | `evaluator.py:324` `_NON_AGENT_DEVICE_TYPES` | E.8 |
| 6 | `last_seen_at`/`last_observed_at` = our fetch time, not platform truth; `device_long_offline` fires on wrong clock | device_links writes, matview, `evaluator.py:471-478` | E.6 |
| 7 | Hostname ambiguity → bail instead of link | `resolver.py` COUNT>=2 skip | E.3 |
| 8 | Identity-pending entities hidden from promotion | `resolver.py` pending_hostnames skip | E.8 |

~~Accepted exception: `bootstrap_clients_from_ninja` — canonical clients
seed from Ninja orgs.~~ **SUPERSEDED 2026-07-13 by Track C**: no source
is a client authority. Ninja orgs flow through `org` observations and
the client resolver like every other source's container; the existing
75 clients + client_links survive as already-accepted state, and the
bootstrap is retired in C.7.

### Future direction (backlog, design must not preclude)

- **Entities beyond devices:** users (AD/M365/Google), software titles,
  network segments — same pattern: streams → correlation → canonical
  entity → coverage questions. Identity layer written so device logic
  is a strategy, not the skeleton.
- **Relationships as edges:** vm.guest names its host → guest-runs-on-host;
  device→assigned-user; device→network. Inventory becomes a map.

**Verify:** ops alive device count = distinct observed hosts (explainable
vs Ninja console: extras are exactly the source-only hosts, each carrying
a finding); UTA servers ≈ 151 Ninja-agented + visible guest/other hosts;
zero devices with 0 links; every unmapped node_class has an admin finding.

### Batches

| Batch | Content | Gate |
|---|---|---|
| E1 | E.1 audit + E.2 writer (dual-write) | observation counts per entity_type match ninja_core node_class counts |
| E2 | E.3 resolver + E.5 repair | inventory counts reconcile; no same-client strict-hostname twins as separate devices |
| E3 | E.4 bootstrap retire + E.6 semantics | one clean cycle; coverage cards match manual console checks |

---

## Track C — Client entity (clients are first-class entities)

Added 2026-07-13. User-set principles governing this track:

1. **A client is an entity like a device.** Every entity type flows
   through the same pipeline: observations → identity resolution →
   lifecycle → findings. Each source emits its *container* as an `org`
   observation (Ninja organization, S1 site, LMI group, SC company/
   instance) exactly as it emits device streams.
2. **NO source authority.** Nobody's org list mints or renames clients.
   Resolution does the work; conflicts become findings. (Supersedes the
   Track E `bootstrap_clients_from_ninja` exception.)
3. **NO auto-mint.** A new name — however many sources corroborate it —
   becomes a **client candidate** requiring operator acceptance
   (accept / map to existing / exclude / fix at source). Client
   onboarding is managed; silent client creation is a bug, not a
   feature.
4. **Mappings live in data, never code.** Every mapping fact (name
   aliases, id-links, excludes, placeholder-name list, suggestion
   preference order, default requirements profile) is a data row with
   an admin surface to view/maintain it. Hardcoded lists like
   `_PLACEHOLDER_ORG_NAMES` (normalize.py:60-68) are the anti-pattern
   and get migrated to tables.
5. **Clean run for clients** like devices got: rebuild client
   resolution from zero and reconcile per-source group counts against
   the consoles.

Why this matters operationally: compliance hangs off clients. No
client on an observation ⇒ no `coverage_requirements` apply ⇒ device
compliance is silently OFF. Today's 24 clientless LMI observations
(11 hosts in groups TSK / Ready / Silk Edge / Silvercup / "-1") are
invisible to compliance even though client "TSK" exists — proving the
name-based learning gap.

### C.1 Entity taxonomy (lock naming now, avoid rearchitecting)

Naming grammar: `<domain>.<stream>`, pinned from live data:

| Entity type | Tier | Today | Notes |
|---|---|---|---|
| `agent.rmm` / `agent.edr` / `agent.remote_access` | 1 (identity+lifecycle) | live | Track E |
| `vm.guest` / `vm.host` | 1 | live (860 / 99) | Track E |
| `network.device`, `monitor.target` | 1 | live (2 / 1) | Track E |
| `org` | 1 | **this track** | source containers → clients |
| `org.location` | 1 | backlog | ninja_core.locations (245) |
| `software` | 1 | partial (P4) | 5,225 titles |
| `policy` | 1 | backlog | ninja_core.policies (90) |
| `user.*` | 1 | future | AD/M365; client_users exists |
| activities / health / patch facts | 2 (measurements) | live | never entities; attach to entities |

Rule: a Tier-1 entity gets identity resolution + lifecycle + findings;
a Tier-2 stream is evidence attached to a Tier-1 entity. New sources
MUST emit their container as `org` observations from day one.

### C.2 `org` observations from every connector

Each connector emits one `entity_observations` row per container per
run, `entity_type='org'`, `entity_key` = the stable group id (Ninja org
id, S1 site id, LMI group id, SC company name/instance), never the
display name. `canonical_data`: name, normalized name
(`normalize_org_name`), device count in group, source-native metadata.
`client_id` left NULL — the client resolver owns attachment.

### C.3 Client resolver (evidence-based, no authority)

New `ingest/identity/client_resolver.py`, run in `drain_resolution`
before device promotion (devices need client scope). Match ladder per
unattached `org` observation:

Rungs are **strictly exclusive** — a hit on a rung short-circuits;
lower rungs never run:

1. **id-link** (proof, survives renames): `operations.client_links`
   row for (source, external group id) → attach, DONE. No name
   matching of any kind runs against a mapped group — a mapping is an
   explicit operator decision (or minted proof) and heuristics never
   second-guess it. Name drift on a mapped group (group name no longer
   equals the linked client's name/aliases — cheap equality check, not
   a matching pass) → `client_name_conflict` finding (C.5) with
   one-click apply; the link holds regardless.
2. **exact normalized name** match to an existing client (canonical
   name or alias row) → attach + create the id-link row so the match
   becomes proof (audited, `created_reason='resolver.name_match'`).
3. **fuzzy / prefix / device-overlap** → NEVER auto-attach. Feeds the
   candidate evidence panel as a suggestion only.
4. No match → client candidate (C.4). Placeholder names (from the
   placeholder table, not code) are excluded from candidacy but still
   visible as unattached observations.

Name tables (all admin-maintainable, per principle 4):

- `operations.client_name_aliases` (client, alias, normalized, tier:
  manual > seed > alignment > source, created_by/reason) — replaces
  legacy `client_aliases` (config_loader.py:158-316).
- `operations.client_org_excludes` (source, external id/name pattern,
  reason) — replaces `org_excludes`.
- `operations.placeholder_org_names` — replaces
  `_PLACEHOLDER_ORG_NAMES`.

### C.4 Client candidates + evidence panel (no auto-mint)

`operations.client_candidates`: (tenant, normalized name, status
open / accepted / mapped / excluded, first_seen, last_seen,
seen_count, per-source group refs JSONB). Re-seen bumps last_seen +
count (legacy org_candidates parity, config_loader.py:319-648).

Acceptance UI shows FULL supporting evidence per candidate:

- per-source records (source, group id, native name, device count,
  first/last seen);
- sample devices in the group (hostnames, platforms);
- **device-overlap signal**: devices in this group whose identity
  already resolves to an existing client's devices → strongest
  map-to-existing evidence (legacy name-matching never had this);
- fuzzy-name suggestions against existing clients + aliases, ranked;
- recommended action.

Operator actions (all audited):

- **Accept** → create client, id-link every contributing source group,
  create alias rows, **assign a requirements profile** (C.6) — a
  client is never born without compliance semantics.
- **Map to existing** → id-link groups to the chosen client + alias
  the name.
- **Exclude** → org_excludes row (reversible: excludes list has
  restore).
- **Fix at source** → candidate stays open with a note; re-resolves
  when the source data changes.

### C.5 Client findings

A name/attachment problem on a KNOWN client is a finding, not a
candidate. Seed finding types (entity class `client`, source_module
`platform.client_resolver`, auto_resolvable):

| Type | Condition |
|---|---|
| `client_name_conflict` | source group renamed away from the linked client's name (e.g. Ninja org rename) — finding + one-click "apply rename" action |
| `client_link_collision` | one source group name-matches ≥2 clients, or two groups from one source claim the same client where the source models 1:1 |
| `client_unattached_group` | non-placeholder group unattached > threshold (candidate exists but stale) |

Legacy demotion-on-collision (promoted candidate colliding with a new
client) becomes `client_link_collision` instead of silent demotion.

### C.6 Requirements assignment fixes (folded in)

`coverage_requirements` semantics today: rows are (entity_type,
platform, device_scope, client_id NULLable); multiple same-type rows
are additive (evaluator.py:457-542 iterates all enabled rows). Two
gaps fixed here:

- **Platform wildcard/list**: `platform` gains `'any'` (any source of
  that entity_type satisfies — "some EDR present") and the evaluator's
  presence join honors it. Specific-platform rows keep meaning "this
  EDR".
- **Override precedence**: client-scoped rows currently ADD to global
  rows; fix so a client row for (entity_type, device_scope) REPLACES
  the global row for that client (documented, tested).
- **Requirements profiles**: `operations.requirement_profiles` +
  profile→requirement template rows; acceptance (C.4) instantiates the
  chosen profile for the new client. **Tenant default profile is a
  data row**, not code.

### C.7 Legacy parity + data migration

From the 23-item agent_compliance inventory
(config_loader.py:158-648, `sync_clients_from_observations`,
`load_id_links`, `load_org_excludes`). Migration (RunPython), imported
as **pre-approved** operator state:

- 273 `client_aliases` → `client_name_aliases` (tier preserved);
- 563 `client_platform_links` → `operations.client_links` id-links
  (rows already partially seeded in 0018 — dedupe on
  (source, external_id));
- 8 `org_excludes` → `client_org_excludes`;
- 151 `org_candidates` history NOT imported — candidates regenerate
  from live observations on the clean run.

Parity behaviors carried: alias tiers, candidate re-seen counting,
enable/disable soft-delete on links, canonical-name preference order
(Ninja > S1 > LMI — as a data row in a preference table, per
principle 4), alignment status per client×source
(MATCHED / FUZZY / MISSING / NA) rebuilt as a view over
client_links + org observations. `bootstrap_clients_from_ninja`
retired from entrypoint after one clean cycle (same pattern as E.4).

### C.8 Clean run + verify

Truncate `org` observations + candidates (keep clients, client_links,
aliases, excludes, requirements), full re-ingest, then gates:

- 75 Ninja orgs reconcile: every org attaches via existing id-links,
  zero new candidates from Ninja names already known;
- TSK / Ready / Silk Edge / Silvercup surface — TSK as a name-match or
  map-to-existing suggestion, the others as candidates with evidence;
- zero silent clientless observations: every unattached `org`
  observation is either a candidate, excluded, or placeholder-listed;
- per-source group counts match the consoles (Ninja orgs, S1 sites,
  LMI groups, SC instances);
- accept one candidate end-to-end: client created, profile
  instantiated, its devices gain coverage evaluation next cycle.

### Batches

| Batch | Content | Gate |
|---|---|---|
| C1 | taxonomy pin + `org` observation emit (all connectors) + name/exclude/placeholder tables + migration | org observation counts = console group counts per source |
| C2 | client resolver + candidates + findings + legacy data migration | 75 Ninja orgs auto-attach via id-links; clientless-LMI groups become candidates |
| C3 | evidence panel + acceptance UI + requirements profiles + wildcard/override fixes | accept round-trip verified; C.8 gates all green |

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

### 1.7 cross_client_conflict findings — REMOVED 2026-07-14

Originally spec'd (from legacy AC ingest.py:516, :608-620): same
`normalize_hostname` resolving to devices under different clients
emits `cross_client_conflict`, severity medium, one per device.

**Removed after operational analysis.** The finding's premise doesn't
survive the ops resolver design:

- The resolver merges cross-source records with matching hardware
  (serial / vm_uuid / MAC) into ONE canonical device at resolve time
  (Track E, resolver.py `_group_same_machine`).
- Therefore two devices with the same hostname across different
  clients can ONLY coexist if they have DIFFERENT (or unknown)
  hardware IDs — i.e., they are genuinely different machines that
  happen to share a generic name (`dc`, `sql`, `fileserver`, `rd`, …).
- Data confirms it: 0 of 1,685 cross-client hostname pairs on this
  fleet had hardware corroboration; 282 open findings were 100%
  naming coincidence.

Legacy AC needed this finding because its resolver did NOT merge by
hardware ID as aggressively; the new resolver eliminates the class of
problem the finding was trying to detect. Migration 0034 resolves
existing findings; emitter deleted from `_evaluate_cross_client`.
Finding type row retained for historical audit only, no re-emission.

If a real cross-client duplicate ever needs surfacing (hardware match
that slipped through resolver, e.g. junk-serial edge cases), the
better shape is an `identity_candidate(device_a, device_b)` with
hardware corroboration in its signals — surfaced through the
identity-review workflow rather than a finding.

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
| PC | Track C batches C1–C3 (client entity) — **priority, before P2** | C.8 clean-run gates green |
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
