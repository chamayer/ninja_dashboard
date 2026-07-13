# Operations Sessions

Detailed Operations module development journal. Root `../SESSIONS.md` keeps
only project-level pointers.

---

## 2026-07-13 (latest) — Track C batch C3: evidence panel + acceptance UI + requirement profiles

**Why:** C1 emitted org observations, C2 resolved id-link + exact-name
+ recorded the residual as candidates + findings. C3 turns those
candidates into decisions and folds in the compliance-shape fixes
(platform 'any' wildcard, client override precedence, tenant-default
requirement profile as a data row).

**Commits:**

- `a61c486` — C3a. `RequirementProfile` +
  `RequirementProfileItem` models; `Client.requirement_profile`
  nullable FK; migration 0029 (RLS + grants, partial-unique
  is_tenant_default) seeds a "Standard" profile from the tenant's
  global coverage_requirements (3 items: agent.rmm/Ninja,
  agent.edr/SentinelOne, agent.remote_access/LogMeIn, all severity
  matched original rows). Evaluator (`_evaluate_coverage`) rewritten:
  LATERAL subquery aggregates `agent_presence_current` per device so
  `platform='any'` correctly means "some platform of this entity_type
  present"; client-scoped requirement rows for (entity_type,
  device_scope) now REPLACE global rows for that client's devices
  (override index built once per pass, COALESCE guards NULL
  client_id + empty override arrays).
- `e760e2b` — C3b. `/clients/candidates/` queue view + evidence
  detail view: per-source group records (device_count, run_count,
  first/last seen from entity_observations), sample devices in the
  group (via `canonical_data->>platform_group_id`), device-overlap
  signal (which existing client's devices already resolve inside
  this group — strongest map-to-existing hint), fuzzy suggestions
  via `difflib.get_close_matches` against Client.display_name and
  enabled `client_name_aliases`. Nav badge from
  `nav_pending_client_candidates` context processor.
- `c5d1c56` — C3c. Four POST endpoints on
  `/clients/candidates/<uuid>/`:
    * `accept`  — mint Client (slugified display_name with -N
      collision suffix), attach every source group via shared
      `_attach_group_to_client` helper (mints client_link with
      `created_reason='candidate.accept'`, backfills org + device
      observations, clears unmatched_source_groups), add manual-tier
      ClientNameAlias, instantiate the chosen profile's items as
      per-client CoverageRequirement rows. Defaults to tenant-default
      profile.
    * `map`     — same attach flow into an existing client, no mint.
    * `exclude` — add `client_org_excludes` row.
    * `fix`     — record operator note only, candidate stays open.
  Every action writes an `AuditLog` row (actor_kind=user, source=ui,
  entity_type='client_candidate', before/after JSON). Detail page
  grows collapsible action forms.

**Verified on am-ch-01:**

Migration 0029 applied; Standard profile with 3 items seeded and
`is_tenant_default=true`. `/clients/candidates/` returns 200.
Wildcard+override evaluator SQL executes cleanly:
`SELECT ... LATERAL ... NOT COALESCE(d.client_id = ANY(ARRAY[]::uuid[]), FALSE)`
matches 5,127 devices (~ full tenant); 4,122 have S1 presence — the
denominator/numerator relationship the wildcard is meant to express.

End-to-end candidate accept via the UI awaits an operator click
(Silvercup, DJ Direct GA, Silk Edge, etc. are ready for review).

**Track C is functionally complete** — every gate from C.8 except
the live accept-round-trip is green. C1 org observations reconcile
per platform; TSK auto-attached by exact name on both S1 + LMI at
C2; candidates surface for the correct residual; profile
infrastructure and evaluator wildcard/override work.

**Next:** await operator use of the acceptance UI, then P2
(notification dispatcher, previously paused for Track E → Track C).

---

## 2026-07-13 (later evening) — Track C batch C2: client resolver + candidates + client findings + legacy import

**Why:** C1 shipped the raw org observations and empty name-mapping tables;
C2 is the engine that turns those observations into decisions. Strictly
exclusive ladder per the tightened C.3: an id-link short-circuits all
matching (drift becomes an operator finding, never a re-match), exact
normalized-name attaches and mints the link, everything else becomes a
candidate.

**Commits:**

- `954d635` — batch C2. `ingest/identity/client_resolver.py`
  (`drain_client_resolution`) with its own `pg_advisory_xact_lock`.
  Wired into `source_run_queue.process_entry` and
  `main.run_identity_resolver_once` to run before device promotion.
  Device observations now carry `canonical_data.platform_group_id`
  so the resolver can backfill devices when it attaches an org.
  Migration 0028: `client_candidates` table with RLS + grants;
  `client_links.created_at` + `created_reason` via
  `SeparateDatabaseAndState`; three finding types
  (`client_name_conflict` entity/medium/auto,
  `client_link_collision` admin/high/manual,
  `client_unattached_group` admin/medium/auto); legacy import — 267
  `client_aliases` rows deduped by tier rank
  (manual > seed > alignment > source) to 50 `client_name_aliases`;
  7 `org_excludes` rows → `client_org_excludes`.
- `04e845c` — fix: `client_candidates.first_seen_at` (Django
  `auto_now_add`) is NOT NULL with no DB default; raw INSERT must
  supply `NOW()`.
- `a74f064` — fix (same class): `resolved_by` and `resolved_reason`
  (`CharField(default="")`) also have no DB default; supply `''`.

**Verified on am-ch-01:**

Rung-2 auto-attaches minted 4 `client_links` with
`created_reason='resolver.name_match'`: TSK on LogMeIn, TSK on
SentinelOne, "Spencer Myrtle / Express Builders" on SentinelOne, Glas
on SentinelOne. C.8 gate: TSK attaches by exact name on both S1 and
LMI without operator intervention.

6 open `client_candidates` (the correct residual): Silvercup (seen 4×,
2 sources), A.M.Rose Internal, DJ Direct GA, Gla, Silk Edge,
Trimworx/Deco/BGG. 7 `client_unattached_group` admin findings
(Silvercup surfaces once per source-binding = 2 findings for 1
candidate). 1 `client_name_conflict` drift finding. 0 collisions.

Placeholders ("Default site" S1, "Unknown"/".Default" LMI) and empty-
name LMI "-1" group correctly stayed out of candidacy.

**Next:** batch C3 — evidence panel + acceptance UI (accept mints
client / map attaches to existing / exclude adds row / fix renames
source-side, all audited) + requirement_profiles + platform-any
wildcard + client-row-replaces-global override semantics.

---

## 2026-07-13 (later) — Track C blueprint + batch C1: org observations, name mapping tables

**Why:** 24 clientless LMI observations proved the client-learning gap —
client "TSK" exists yet LMI group "TSK" sat unmatched, and no client means
zero compliance evaluation. User set the track's principles: clients are
first-class entities (observations → resolution → lifecycle → findings),
NO source authority (supersedes the bootstrap_clients_from_ninja
exception), NO auto-mint (every new name is a candidate needing
acceptance), all mappings in admin-maintainable data, id-link mappings
short-circuit all matching (name drift = finding, never re-match).

**Commits:**

- `3a4f10d` — BLUEPRINT Track C written (C.1 entity taxonomy pin, C.2 org
  observations, C.3 strictly-exclusive resolver ladder, C.4 candidates +
  evidence panel, C.5 client findings, C.6 requirement profiles +
  platform-any wildcard + client override semantics, C.7 legacy parity
  migration 273/8 rows, C.8 clean-run gates; PC batch row before P2).
- `500e419` — batch C1: every source emits one `entity_type='org'`
  observation per container per run keyed by stable group id (Ninja: all
  ninja_core.organizations incl. empty; S1: /sites fetch so zero-agent
  sites observed; LMI: payload groups list incl. empty; SC: one per
  client-scoped instance). Migration 0027: client_name_aliases /
  client_org_excludes / placeholder_org_names (+RLS/grants, placeholder
  seed); hardcoded `_PLACEHOLDER_ORG_NAMES` deleted — writer reads the
  table. `_org_only` fetcher row contract for container-only records.
  Device resolver queries exclude `entity_type='org'` (containers resolve
  to clients in C2, not devices). Attachment at write is rung 1 only
  (existing client_links / client-scoped instance); client_id stays NULL
  otherwise for the C2 resolver.

**Verified (first post-deploy run):** Ninja 75/75 org obs attached =
console exact; SC 1/1; S1 78 sites/run (71 attached, 7 unattached incl.
TSK/SilverCup/Glas/"Default site" flagged placeholder); LMI 102 groups
(92 attached; unattached = TSK/Ready/Silk Edge/Silvercup with devices,
4 empty groups, junk "-1", placeholders "Unknown"/".Default" flagged).
0 new devices, 0 orphans, resolver untouched by org rows. S1 appearing
2× = two runs (startup + enqueue) — per-run time series, by design.

**Next:** C2 — client resolver + candidates + client findings + legacy
alias/exclude import.

---

## 2026-07-13 — Confidence-tiered dup collapse; stream-agnostic grouping; rebuild #5

**Why:** UTA showed 135 server rows vs 110 in the Ninja console — 24 phantom
rows were duplicate S1 agent records on reprovisioned Citrix VDI hosts
(same serial + MAC, new agent uuid daily, old record `isActive=false`).
User approved hardware-proof collapse: "yes, but at the same time make sure
that dups and offline are findings."

**Design:** records proven to be ONE machine (equal usable serial, equal
vm_uuid, or shared MAC) collapse onto one device with a link per record —
`duplicate_platform_record` keeps firing (observation-level, now with
per-record `is_online`/`last_seen_at`/serial + `offline_count`). Unproven
same-hostname records stay separate device rows. Proof is **stream-agnostic**
(citrixapp26: Ninja agent.rmm + vm.guest + S1 records share one MAC = one
machine), so machine groups are built across the whole (client, hostname)
cluster before stream-coverage rules apply.

**Commits:**

- `3d6002f` — MAC extraction (`normalize_mac`/`extract_macs` incl. SC
  `GuestInfo.HardwareNetworkAddress`, S1 `networkInterfaces[].physical`,
  Ninja `mac_addresses`); serial-proof merges bypass same-stream guard;
  `_group_same_machine` / `_promote_entry_groups` / `_same_machine_on_device`;
  dup finding enriched with records[] + offline_count.
- `ca22875` — ScreenConnect connector emits EVERY live session (fetch-time
  hostname dedup removed); `GuestInfo.MachineSerialNumber` → canonical serial.
- `671e206` — stream-agnostic cluster grouping; entity_keys already in
  device_links backfill instead of minting orphans; ambiguity-scatter branch
  removed (proven groups merge normally, unproven extras get own rows).
- `6870b28` — `pg_advisory_xact_lock` serializes device promotion: the source
  queue drains resolution one thread per source, and racing promotions minted
  35 orphan devices (no links, no obs) in rebuild #5. Orphans deleted.

**Rebuild #5 verified:** 5,120 devices, 0 orphans. UTA servers 135 → 110
(matches Ninja console). citrixapp26: 7 rows → 1 device (rmm + vm.guest via
MAC + S1 + LMI). Unassigned obs: 24 LMI clientless (unmatched group, by
design) + 9 nameless Ninja vm.guests.

**Open items:** ScreenConnect fetch returned exactly 1,000 sessions twice —
suspected API page cap, verify against SC console. Raw-payload audit found
unmapped matching/finding fields (S1 `machineSid`, `infected`/`activeThreats`,
agent version/scan staleness, encryption; SC `LastBootTime`,
`IsLocalAdminPresent`, model/manufacturer) — candidates for new findings.

---

## 2026-07-12 (later) — Rebuild #1 corrupted; identity rule hardened; rebuilds #2/#3

**Why:** User compared the dashboard against the Ninja console: "i see in
ninja 110 servers for UTA and you show only 97." Investigation showed the
first rebuild (5,075 devices, below) was **corrupted** — BIOS placeholder
serial `'None'` (108 records) merged ~100 UTA servers into one device.
User then issued two hard rules: same-platform hostname dups must NOT be
merged ("it is a valid finding but i need EVERY ROW ACCOUNTED FOR. THEY ARE
CONSUMING LICENSES") and "hostname matches should only be used cross source
... NEVER IN THE SAME SOURCE."

**Work completed (commits `3a7168a`, `11202d3`, `00b0c05`, `efe8ecb`):**

- `3a7168a` — `is_usable_serial()` junk-serial guard in `ingest/normalize.py`
  ('None', 'Default string', 'To Be Filled By O.E.M.', <4 chars,
  single-repeated-char). Junk serials never drive a match.
- `11202d3` — `_sync_device_attributes()` in the resolver: role/device_type/
  os backfill each cycle so attach-path devices aren't frozen at whatever
  the first-resolving source knew (UTA showed only 40 role=server despite
  108 correct devices).
- `00b0c05` — same-stream separation: two records of one
  (platform, entity_type) stream sharing a hostname/serial get SEPARATE
  device rows (`_same_stream_conflict` in resolver + fast_path guards);
  cluster promotion keeps newest per stream, promotes extras individually;
  new `duplicate_platform_record` admin finding (evaluator section 2d,
  migration 0026, severity high for agent streams). Cross-stream merging
  (Ninja agent.rmm + vm.guest = one machine) preserved.
- `efe8ecb` — ambiguous-hostname clusters (≥2 existing devices share the
  hostname) promote every entry individually instead of hanging unresolved
  (10 UTA CTXDESKTOP records were stuck after rebuild #3's mid-ingest
  resolver pass).

**Final verified state (rebuild #3 + efe8ecb pass):** 5,168 devices.
UTA: 110 Ninja WINDOWS_SERVER records → exactly 110 devices, 0 unresolved.
Ninja: 5,458 distinct non-software records → 4,842 distinct devices
(607 cross-stream merges) + 9 nameless vm.guests visible as unresolved.
39 duplicate_platform_record findings open. Unresolved fleet-wide: 18
with-client (nameless) + 24 clientless — visible by design.

**Lesson:** always verify per-device merge traces against source console
counts; never accept plausible aggregate explanations. The "5,075 devices /
UTA 981→948 by design" numbers in the entry below are superseded.

**Next:** P2 notification dispatcher (uncommitted NOTIFY_* prep in
`ingest/config.py`). Residual: attach-path match_method mislabel persists.

---

## 2026-07-12 — Track E completed: E2 deployed, E2b clean rebuild, E3 bootstrap retired

> **Superseded (same day):** the rebuild numbers below were corrupted by the
> junk-serial bug — see the entry above.

**Why:** Finish Track E end-to-end (user-directed autonomous completion).
Codex had shipped most of E2 (commits `96f83b8..ba602ef`: migration 0024,
client-scoped resolver with match method/confidence, form-factor
device_type, lifecycle field, legacy AC scheduler off); this session audited
that work, closed its gaps, and ran the approved clean rebuild.

**Work completed (commits `8b7c986`, `d50ad4d`):**

- Migration 0025: `agent_presence_current` covers every non-software entity
  stream (drops the `agent.%` filter) and adds `last_contact_at` from
  platform truth (`canonical_data->>'last_seen_at'`). Seeds the
  `unmapped_node_class` admin finding type.
- Coverage presence is keyed on (platform, entity_type, scope) so vm/network
  streams don't inflate agent coverage; fleet source reach stays
  agent-scoped.
- Evaluator: `_sync_lifecycle_status` (active <7d / offline_aging 7–30d /
  pending_cleanup >30d from last platform contact; `retired` never touched)
  and `_evaluate_unknown_entities` (admin finding per unmapped node_class;
  currently zero — all node_classes map).
- E2b clean rebuild executed on prod: truncated devices/device_links/
  entity_observations/findings/admin_findings/identity_candidates/
  notification_state+events/merge_candidates/unmatched_source_groups/
  dead_letter_observations; kept clients (75), client_links (239),
  coverage_requirements (17), rules, users. Full re-ingest + resolver +
  evaluator from zero: 5,075 devices, 13,513 links, 1 linkless device,
  30 unresolved observations (12 clientless LogMeIn hostnames + 18 nameless
  Ninja vm.guests — correctly visible, not guessed). UTA gate: 981 Ninja
  agent records → 948 canonical devices (33 same-hostname records linked,
  by design); lifecycle 4,381 active / 264 offline_aging / 433
  pending_cleanup after first sync.
- E3: entrypoint no longer runs `bootstrap_devices_from_ninja` (devices are
  created only via observations + resolution; command kept for manual
  link-integrity). Device page shows per-stream platform last-contact and
  per-link match method/confidence.

**Known residuals:** attach-path labels serial/vm_uuid matches as
`hostname_strict` (cosmetic); cross-client same-hostname candidate creation
dropped by Codex (cross_client_conflict evaluator still covers it); one
linkless device (`naftali2-pc`) from link reassignment — will surface as
stale.

**Next:** P2 notification dispatcher (uncommitted NOTIFY_* prep already in
`ingest/config.py`).

---

## 2026-07-10 — Track E E2 prepared: identity/model correction

**Why:** Live data showed inflated inventory and unreliable coverage because
canonical devices still encoded agent presence in `device_type`, Ninja was
being treated too much like one flat RMM source, and identity matching could
fall through to global hostname/serial matches.

**Work prepared locally (not committed/pushed yet):**

- Migration 0024 adds `devices.lifecycle_status`,
  `device_links.match_method`, and `device_links.match_confidence`; remaps
  `vm-with-agent` / `vm-agentless` to pure `vm`.
- `Device.DeviceType` is now form factor only:
  physical / vm / hypervisor-host / network-device / unknown.
- Ninja observations carry `entity_type` from `node_class` and store
  server/workstation as `device_role`, not `device_type`.
- Shared-source observations now compute client mapping before fast-path
  identity resolution; serial/hostname matching is client-scoped and
  clientless observations stay unresolved.
- Resolver now considers all entity streams, adds VM UUID matching, attaches
  same-client same-hostname observations as additional links, records match
  method/confidence, and promotes unmatched visible entities without the old
  pending-hostname suppression.
- Coverage cards and drilldowns no longer hide devices by form factor;
  requirement `entity_type` is carried into missing-platform URLs. Retired
  lifecycle is the denominator exclusion.
- `bootstrap_devices_from_ninja` no longer creates devices; it is only a
  temporary link-integrity/canonical refresh path until E3 removes it from
  startup.

**Checks:** `python manage.py check`, targeted `py_compile`, and targeted
ruff checks for new resolver/migration issues pass. Full
`makemigrations --check --dry-run` still reports pre-existing model drift
around inherited `version` fields/options on platform tables, unrelated to
Track E.

**Next:** commit/deploy this Track E set only, run migration 0024, then do
the approved clean rebuild/re-ingest from corrected writers and verify counts
from zero before resuming P2 notifications.

---

## 2026-07-09 — Batch P1: evaluator parity live + device promotion + client-page card audit

**Why:** Track 1 (evaluator parity) per BLUEPRINT P1; then user found the
client-page coverage numbers wrong (S1 servers showed 15/122 while
SentinelOne really had 98 servers at UTA) and asked for a full card
accuracy + clickthrough review.

**Work completed (commits `ad31d5b`, `47f3be7`, `6346321`, `d72d0be`,
`a6c3827`, `c8ca279`):**

- Migration 0023 (device_role/exemptions/finding types) — fixed
  psycopg3 placeholder crash by passing `params=None` to
  `schema_editor.execute` for raw SQL containing literal `%`.
- **Device promotion span killed** (`ingest/identity/resolver.py`):
  unresolved observation clusters now promote to canonical devices on
  first observation — every source row comes from an authoritative
  platform inventory, so an unmatched hostname is a real device (legacy
  parity). Safeguards kept: serial match, hostname match, ambiguity
  skip → identity_candidates.
- New operator endpoint `POST /run/resolver` on operations-ingest
  (127.0.0.1:8090) for on-demand resolution/promotion. Resolver also
  runs immediately after every source fetch; the 30-min job is a
  backstop.
- Forced promotion created **3,213 devices** fleet-wide (multi-source
  clusters merged into single devices with per-platform device_links).
- Client-page card audit: Software tile now shows real distinct-title
  count; coverage universe made form-factor based (excludes
  network-device/hypervisor-host/vm-agentless) on both sides of the
  ratio; coverage scope rows are now clickthrough links to
  `/orgs/<slug>/devices/?missing=<platform>&role=<role>`; org_devices
  gained `role` and `missing` filters + Role column.
- Evaluator hardening (three prod-verified fixes): admin_findings
  insert supplies `version=1` (physical NOT NULL without default);
  findings upsert uses partial-unique-index inference
  (`ON CONFLICT (tenant_id, condition_key) WHERE condition_key > ''
  AND status IN ('open','acknowledged')`); nullable uuid params cast
  `%s::uuid` to avoid psycopg3 IndeterminateDatatype.

**Verified in prod:** UTA S1 servers went 15/122 → **102/209**;
unknown-role S1 devices eliminated; LMI servers 1 → 50. First full
evaluator run: findings_affected=1601, no skipped platforms. Open
findings: cross_client_conflict 718 (over-firing on generic hostnames —
needs tuning), device_long_offline 630, device_missing_from_source 240,
device_role_conflict 13.

**Follow-ups:** cross_client_conflict tuning; missing_required_platform
findings will appear as promoted devices age past gap thresholds;
one-off gunicorn worker timeout during matview refresh (if recurring,
make refresh CONCURRENTLY); Batch P2 = Track 2 notification dispatcher.

---

## 2026-07-08 — Software inventory page (0.43.0)

**Work completed:**

- `views.py`: `org_software` view — raw SQL against `software_installations_current`
  with SET LOCAL RLS setup inside `transaction.atomic()`. Aggregates by
  (canonical_name, publisher), returns device_count, versions, last_seen.
  Name search + publisher filter + manual pagination (100/page).
- `config/urls.py`: `/orgs/<slug>/software/` → `org_software`.
- `templates/org_software.html`: table with search/publisher filter form,
  pagination, and empty-state message pointing to `SOFTWARE_QUEUE_ENABLED`.

**Status:** Deployed. Will show empty until `SOFTWARE_QUEUE_ENABLED=true` is
set in server `.env` and ingest redeployed + first sweep completes.

---

## 2026-07-08 — Batch E Phase 12 (container rename)

**Why:** Naming cleanup — align Docker container name with the
`operations-*` convention established for the rest of the stack.

**Work completed:**

- `docker-compose.yml`: `container_name: ninja-ingest` → `operations-ingest`.
- `HANDY_COMMANDS.md`: all `docker exec ninja-ingest` examples updated.
- `ingest/` module docstrings (7 files): all `docker exec ninja-ingest`
  examples updated to `operations-ingest`.
- `TROUBLESHOOTING.md`: updated one `docker exec ninja-ingest` example.

**Status:** Phase 12 complete. Phases 13–14 require operator coordination
(see TODO.md Backlog — Phase 13 needs `.env` change on am-ch-01 first).

---

## 2026-07-08 — Batch D (Phase 11)

**Why:** Findings review and admin health pages — first UI surface for the
platform evaluator output.

**Work completed:**

- Enhanced /findings/ view: added confidence, client, type filters; pagination
  (50/page); shows hostname from finding_details; one-click Ack button.
- New /admin/findings/health/ view: shows AdminFinding records (platform-level
  issues), severity/status/type filters, Ack button.
- New POST /findings/<id>/ack/ and /admin/findings/<id>/ack/ acknowledge endpoints.
- Updated urls.py with 4 new routes.
- Updated findings_queue.html template and added findings_admin_health.html.

**Deployed:** v0.41.0

---

## 2026-07-08 — Batch C (Phases 8–10)

**Why:** Platform evaluator, compliance engine rebuild, agent_presence_current
materialized view.

**Work completed:**

- Phase 8: ingest/evaluator.py — platform evaluator with coverage gap analysis,
  device lifecycle findings (missing_from_source, long_offline), and
  auto-resolve. Wired into main.py APScheduler (every 4h).
- Phase 9: ingest/agent_compliance/ingest.py — calls platform_evaluate() after
  each full AC run. Also refreshes agent_presence_current.
- Phase 10: migration 0016 — creates operations.agent_presence_current
  materialized view aggregating agent.* entity_observations per device per
  platform. CONCURRENT refresh function. Grants to all reader roles.

**Deployed:** v0.40.0

---

## 2026-07-08 — Batch B (Phases 5–7)

**Why:** Data sync: keep operations.device_links in sync with Ninja pull,
seed S1/SC/LMI source bindings, dual-write AC observations into
operations.entity_observations, ship identity fast_path and polling resolver.

**Work completed:**

- Phase 5: _sync_operations_device_links() added to ingest/core/devices.py —
  three UPDATE statements inside the existing Ninja device transaction to keep
  operations.device_links.last_seen_at/missing_since in sync.
- Phase 6: ingest/identity/__init__.py + fast_path.py + resolver.py — inline
  device resolution (source link → serial → hostname) and polling v1 resolver
  for entity_observations with NULL device_id.
- Phase 7: migration 0015 seeds SentinelOne/ScreenConnect/LogMeIn source
  bindings with fixed UUIDs. ingest.py dual-writes AC observations into
  operations.entity_observations for S1/SC/LMI platforms.

**Deployed:** v0.39.0

---

## 2026-07-08 — Platform foundation Batch A3 (Phase 4)

**Why:** Create all new platform tables needed by the evaluator, identity
resolver, queue governance, and notification engine.

**Work completed:**

- Migration 0014: CreateModel for 7 new tables — CoverageRequirement,
  AdminFinding, QueueRegistry, IdentityCandidate, NotificationRule,
  NotificationState, NotificationEvent. Unique/index constraints added.
  RunPython enables RLS + grants on 6 tenant-scoped tables (not queue_registry).
  RunPython seeds 4 queues into queue_registry.
- models.py: 7 new model classes added (CoverageRequirement, AdminFinding,
  QueueRegistry, IdentityCandidate, NotificationRule, NotificationState,
  NotificationEvent).

**Deployed:** v0.38.0

---

## 2026-07-08 — Platform foundation Batch A2 (Phase 3)

**Why:** Extend FindingType and Finding models with platform evaluator fields —
finding_class/source_module/auto_resolvable on types; condition_key/confidence/
last_detected_at/client FK on findings. Seed 6 new finding types.

**Work completed:**

- Migration 0013: AddField finding_class, source_module, auto_resolvable on
  FindingType. AddField condition_key (with unique partial constraint on active
  findings), confidence, last_detected_at, client FK on Finding.
  RunPython back-fills all 10 existing types with entity class + source_module.
  Inserts 6 new finding types (4 entity, 2 admin).

**Deployed:** v0.37.0

---

## 2026-07-08 — Platform foundation Batch A1 (Phases 1–2)

**Why:** Three-state staleness model for software_installations_current (fixes
active data-loss risk — refresh function was hard-deleting missing rows).
Universal lifecycle columns on devices, device_links, and clients per DESIGN.md §3.4.

**Work completed:**

- Migration 0011: rewrote `operations.refresh_software_installations_current()`
  to use stale/unmark pattern instead of DELETE. Added stale_since, stale_reason,
  deleted_at, deleted_reason columns to software_installations_current.
- Migration 0012: added missing_since to device_links; added created_at,
  created_reason, updated_at, updated_reason, stale_since, stale_reason,
  deleted_reason to both devices and clients.
- Updated models.py to reflect all new fields.

**Deployed:** v0.36.0

---

## 2026-07-07 — Fleet overview dashboard

**Why:** The all-clients view was a plain flat table. With Operations
reframed as a data browser, the front door should show fleet state at a
glance.

**Work completed:**

- Added 4 summary tiles to the all-clients view: Clients, Devices (with
  type breakdown), Sources (distinct sources with per-source client count),
  Findings (global open count).
- Added Sources column to the client table showing which systems each
  client is linked to.
- Moved shared tile CSS out of the per-client branch so both views share it.
- Removed slug column from client table (slug belongs on the detail page,
  not the fleet list).

**Validation:** Django check, ruff, template load smoke test all passed.

**Deployed:** `8b452f7`, pushed to both remotes. Browser check pending.

---

## 2026-07-07 — Product direction reframed to operational data app

**Why:** We were drifting toward describing Operations as mainly an issue
resolution console. The intended product is broader: it should become the
primary app for viewing and working with the operational data model.

**Decision:**

- Operations is the operational data browser and control plane.
- Operators should use it to view current canonical clients, devices, users,
  software, sources, observations, evidence, status, history, findings, and
  decisions.
- Metabase remains useful for exploratory BI, broad historical analytics, and
  arbitrary charting.
- Operations pages should be model-aware and workflow-aware. If a page helps
  someone understand or operate the managed environment, it belongs here. If it
  is only a generic chart over arbitrary data, it likely belongs in Metabase.

**Pending:** Next approved UI slice should start from this framing, likely a
top-level Operations dashboard/data-browser front door.

---

## 2026-07-07 — Client landing identity coverage WIP

**Why:** The client landing page only showed canonical client identity and
`client_links`. That was too thin for Operations' purpose as the
operator-facing identity-resolution surface.

**Work completed locally:**

- Added identity coverage aggregates to `org_index` for:
  - device source links by source;
  - source binding enabled/disabled counts;
  - canonical client users and external user links;
  - active `unlinked_external_identity` findings tied to this client's
    source bindings.
- Added a compact "Identity coverage" section to the per-client landing page.
- Kept the change summary-level; no new detail pages or schema changes.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- `python -m ruff check operations\apps\core\views.py` passed.
- Template load smoke for `org_index.html` passed.

**Deployed:** Committed as `a8bf257`, pushed to both remotes, Portainer
auto-update deployed it. Container healthy. Browser validation pending.

---

## 2026-07-07 — Device list pagination/search WIP

**Why:** Live Operations logs showed `/orgs/uta/devices/` returned a large
device-list page and a Gunicorn worker timed out shortly afterward. The view
loaded every device for a client and filtered rows in browser JavaScript.

**Work completed locally:**

- Changed `org_devices` to filter/search/paginate in Django instead of
  materializing all client devices.
- Added server-side search by hostname/serial.
- Added server-side device type filtering.
- Added pagination at 100 devices per page.
- Updated the device-list template to use GET controls and pagination links.
- Added backlog notes for broader client identity coverage and a future
  top-level Operations summary page.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- `python -m ruff check operations\apps\core\views.py` passed.
- `python operations\manage.py shell --settings=config.settings.dev -c "from django.template.loader import get_template; get_template('org_devices.html'); print('template_ok')"`
  passed.

**Live validation:** Portainer deployed `cfa1767`; `/orgs/uta/devices/`
returned 47,649 bytes versus the previous 504,547-byte render. Operations
remained healthy. A later Gunicorn timeout showed `no URI read`, so it was
recorded as non-blocking idle connection noise, not a page render failure.

**Pending:** None for this slice.

---

## 2026-07-07 — Live Operations validation

**Why:** Continue the active checkpoint after pushing `55cda73`.

**Validation completed:**

- Pushed docs checkpoint `55cda73` to both `origin/master` and
  `a-m-rose/master`.
- Configured SSH key login from the workstation to `amrose@10.61.50.28` via
  local alias `am-ch-01`.
- Confirmed SSH login lands on host `am-ch-01` as `amrose`, with `docker`
  group membership available.
- Confirmed Operations is reachable from the workstation at
  `http://10.61.50.28:3002/`.
- Confirmed Gunicorn serves the app and unauthenticated `/` and
  `/orgs/all/` requests redirect to `/admin/login/`.
- Confirmed `ninja-operations`, `ninja-ingest`, `ninja-metabase`, and
  `ninja-postgres` containers are running healthy.
- Confirmed host-loopback health:
  `curl -fsS http://127.0.0.1:8091/healthz` returned `{"status": "ok"}`.
- Confirmed all Operations migrations through `0009_rename_device_kind_to_device_type`
  are applied.
- Confirmed startup logs show:
  - migrations ran as `operations_migrate`;
  - initial admin password sync skipped because already current;
  - client bootstrap saw `created=0 updated=0 unchanged=75 total=75`;
  - device bootstrap saw `created=0 updated=2 unchanged=5656 orphaned=0 total=5658`;
  - static files collected and Gunicorn started.
- Confirmed Postgres counts:
  - `operations.clients`: 75
  - `operations.client_links`: 75
  - `operations.devices`: 5658
  - `operations.device_links`: 5658

**Notes:**

- Plain `docker ...` works over SSH because `amrose` is in the `docker`
  group; do not use `sudo docker ...`.
- Django ORM counts from the runtime app role can return zero without tenant
  context because RLS is active. Use `tenant_context(1)` or Postgres-side
  count queries for validation.
- SSH commands currently print a local `known_hosts` update warning even when
  the remote command succeeds:
  `hostfile_replace_entries: mkstemp: Permission denied`.
- Logs contain one Gunicorn worker timeout at `2026-07-07 16:49:44` after a
  large `/orgs/uta/devices/` page response; service recovered and health
  checks continued passing.

**Pending:** User-facing same-password redeploy session preservation still
needs browser confirmation after a future Portainer redeploy.

---

## 2026-07-07 — Checkpoint docs reconciled to committed Operations state

**Why:** The active build blueprint and TODO still described M0.11/M0.12/M0.15
as pending, but the commit history showed M0.11/M0.12, device bootstrap, and
several M1 UI/data pages were already committed and pushed.

**Work completed locally:**

- Updated `operations/BUILD_BLUEPRINT.md` to make live Portainer validation
  the active checkpoint.
- Moved obsolete M0.11/M0.12/current-WIP items out of `operations/TODO.md`.
- Recorded completed Operations slices through `746770e`.

**Current checkpoint:**

- Validate commit `746770e` in the Portainer-managed `ninja-dashboard` stack.
- Confirm migrations/bootstrap, `/healthz`, populated clients/devices, and
  same-password redeploy session preservation.
- Choose the next M1 implementation slice only after that validation is known.

**Validation:** Documentation-only change; no code checks required.

**Pending:** Live Portainer validation.

---

## 2026-07-07 — Admin session preservation across redeploys

**Why:** The Operations container startup command re-applied the initial admin
password on every redeploy. Django salts each password hash, so even the same
password produced a new stored hash and invalidated existing admin sessions.

**Work completed locally:**

- Updated `set_initial_admin_password` to check the current admin password
  before calling `set_password()`.
- Kept flag repair behavior for `is_active`, `is_staff`, and `is_superuser`.
- Added command output that reports whether the password or flags changed.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- A targeted two-run command test confirmed the second run skips and the
  stored password hash remains unchanged.
- `python -m ruff check operations` still fails on pre-existing unrelated lint
  in `forms.py`, `views.py`, and `bootstrap_devices_from_ninja.py`.

**Pending:** Browser-confirm same-password redeploy session preservation after
a future Portainer redeploy. Commit `746770e` has been pushed to both remotes.

---

## 2026-07-06 — M0 deployability checkpoint

**Why:** We realized M0 cannot be considered healthy just because schema
migrations validate locally. The blueprint requires a Portainer-deployed
Operations container, and the M0.8 RLS/role migration cannot safely run under
the runtime `operations_app` role.

**Work completed locally:**

- Updated `operations/entrypoint.sh` to run migrations with
  `OPERATIONS_MIGRATE_DB_USER` / `OPERATIONS_MIGRATE_DB_PASSWORD`, then switch
  back to `OPERATIONS_DB_USER` / `OPERATIONS_DB_PASSWORD` before launching
  Gunicorn.
- Updated `operations/config/settings/prod.py` to require both runtime and
  migration DB passwords in production.
- Updated `docker-compose.yml` comments to document the Portainer `.env`
  contract for both role pairs.

**Required `.env` keys for deploy:**

- `OPERATIONS_DB_USER=operations_app`
- `OPERATIONS_DB_PASSWORD=...`
- `OPERATIONS_MIGRATE_DB_USER=operations_migrate`
- `OPERATIONS_MIGRATE_DB_PASSWORD=...`
- Existing required keys still apply: `OPERATIONS_SECRET_KEY` and
  `OPERATIONS_ALLOWED_HOSTS`.

**Validation:** Local Docker is unavailable on this workstation, so container
build/start was not exercised here. Python/Django validation remains required
after this change.

**Pending:** Build/start through Docker or Portainer on a Docker-capable host,
then hit `/healthz` on `127.0.0.1:8091`.

---

## 2026-07-06 — M0.10 seed groups, permissions, and taxonomy

**Why:** Continue the approved Operations M0 build after middleware. M0.10
adds idempotent seed data for local auth groups/permissions and the initial
source/collector/finding taxonomy.

**Work completed locally:**

- Added migration `0007_seed_m0_reference_data`.
- Seeds default tenant `id=1`, `slug=amrose`.
- Creates/updates the 15 custom Operations permissions from §5.4 on the
  `operations.User` content type.
- Creates global Django groups:
  - `admin` with all custom Operations permissions.
  - `operator` with `view_*`, decision, merge, finding, client policy, and
    query permissions.
  - `viewer` with `view_*` and `run_queries`.
- Seeds `sources`: `Ninja`.
- Seeds `collectors`: `internal-ingest`, `ninja-hosted-script`.
- Seeds one tenant-scoped `collector_instances` row for `internal-ingest`.
- Seeds the 10 baseline `finding_types` with runbook paths.
- Seeds an `admin` superuser with an unusable password for break-glass setup
  until a real password is set intentionally.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0007`
  to the local SQLite skeleton.
- Local seed sanity check confirmed: 1 tenant, groups
  `admin`/`operator`/`viewer`, `Ninja` source, 2 collectors, 1 collector
  instance, 10 finding types, and admin user present.

**Pending:** M0.11 bootstrap clients from `ninja_core.organizations`.
Requires approval before implementation.

---

## 2026-07-06 — M0.9 tenant/client-scope middleware

**Why:** Continue the approved Operations M0 build after RLS roles/policies.
M0.9 adds runtime tenant scoping, client-scope resolution, management-command
tenant context helpers, query helpers, and scope decorators.

**Work completed locally:**

- Added `apps.core.db.tenant` with:
  - `set_local_tenant(tenant_id)`
  - `current_tenant_id()`
  - `tenant_context(tenant_id)`
  - `client_scoped_query(request, sql, params)`
  - `all_clients_query(sql, params)`
  - development query-time tenant GUC assertion wrapper.
- Added `TenantMiddleware`.
  - Resolves tenant from authenticated user when present, otherwise tenant 1.
  - Opens the outer transaction itself on Postgres before issuing
    `SET LOCAL operations.tenant_id = %s`, because Django `ATOMIC_REQUESTS`
    wraps views but not normal middleware.
  - Skips the wrapper on `/healthz`.
- Added `ClientScopeMiddleware`.
  - Resolves `/orgs/all/...` to all-client mode.
  - Resolves `/orgs/{slug}/...` to `request.current_client`.
- Added `require_client_scope` and `require_admin` decorators.
- Wired middleware into `config/settings/base.py` after authentication.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` reports no planned operations.

**Pending:** M0.10 admin seed groups, permissions, taxonomy, and finding
types. Requires approval before implementation.

---

## 2026-07-06 — M0.8 RLS roles, policies, and grants

**Why:** Continue the approved Operations M0 build after M0.7 workflow/audit
tables. M0.8 adds the Postgres role, RLS, and privilege layer required by
§6.3 and the M0 DB grants section.

**Work completed locally:**

- Added migration `0006_rls_roles_policies_grants`.
- Postgres-only migration path ensures roles exist:
  `operations_app`, `operations_migrate`, `operations_readonly`,
  `operations_health`, `metabase_ro`, and `ninja_ingest`.
- Enables and forces RLS on tenant-scoped tables with a fail-closed
  `tenant_isolation` policy using
  `current_setting('operations.tenant_id', TRUE)::bigint`.
- Enables and forces RLS on `software_catalog` with a layered
  `tenant_or_global` policy.
- Applies broad app/read-only grants and restricted `ninja_ingest` grants for
  `entity_observations`, `dead_letter_observations`, `run_log`, and
  `refresh_software_installations_current(bigint)`.
- SQLite/local migration path no-ops the Postgres SQL.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0006`
  to the local SQLite skeleton.

**Pending:** M0.9 tenant/client-scope middleware and tenant context helpers.
Requires approval before implementation.

---

## 2026-07-06 — M0.7 workflow and audit tables

**Why:** Continue the approved Operations M0 build after M0.6 observation
tables. M0.7 adds the operator workflow, catalog, findings, notification,
secret, audit, and run tracking tables.

**Work completed locally:**

- Added `SoftwareCatalog` as the layered global/tenant taxonomy table with
  partial uniqueness for global and tenant rows.
- Added `SoftwareDecision`.
- Added `MergeCandidate` with `member_snapshots` and historical
  `member_observation_ids`.
- Added `Finding` with subject polymorphism fields and finding details JSON.
- Added `SuppressionRule`, `NotificationRoute`, `Secret`, `AuditLog`, and
  `RunLog`.
- Added admin registrations for all M0.7 tables.
- Added migration
  `0005_notificationroute_auditlog_finding_mergecandidate_and_more`.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0005`
  to the local SQLite skeleton.

**Pending:** M0.8 RLS roles, policies, and grants. Requires approval before
implementation.

---

## 2026-07-06 — M0.6 observations and current-state table

**Why:** Continue the approved Operations M0 build slice after the module-doc
checkpoint. M0.6 adds the ingest observation landing tables and the
software-install current-state table/function required by §4.5 and §4.7.

**Work completed locally:**

- Added `EntityObservation` with promoted nullable `client_id` and
  `device_id`, collector/source binding references, raw/canonical JSON, batch
  idempotency fields, and the unique key
  `(tenant_id, collector_instance_id, batch_id, observation_hash)`.
- Added `DeadLetterObservation` for unresolved/rejected ingest envelopes.
- Added admin inspection surfaces for both tables.
- Added migration `0004_deadletterobservation_entityobservation`.
- Added Postgres-only migration SQL for
  `operations.software_installations_current` with composite primary key
  `(tenant_id, client_id, device_id, canonical_name)`.
- Added Postgres-only
  `operations.refresh_software_installations_current(bigint)` as a
  `SECURITY DEFINER` function. SQLite/local migration planning no-ops this
  SQL path.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` passed.

**Pending:** M0.7 workflow/audit tables. Requires approval before
implementation.

---

## 2026-07-06 — M0.3-M0.5 local build WIP

**Why:** Resume Claude handoff `a2a3de93-e7af-4d46-a2dd-b2c156f12c9a` for
the Operations M0 build.

**Work completed locally:**

- M0.3 custom auth/tenant foundation:
  - `Tenant`
  - custom `operations.User`
  - tenant-scoped `UserGroup` / `UserPermission`
  - `AUTH_USER_MODEL`
  - admin wiring
  - migration `0001_initial`
- M0.4 canonical entity/link foundation:
  - `Source`
  - `Client`, `ClientLink`, `ClientPolicy`
  - `Device`, `DeviceLink`
  - `ClientUser`, `ClientUserLink`
  - admin wiring
  - migration `0002_source_client_clientpolicy_clientuser_device_and_more`
- M0.5 source/collector taxonomy and binding foundation:
  - `Collector`
  - `FindingType`
  - `SourceInstance`
  - `CollectorInstance`
  - `SourceBinding`
  - admin wiring
  - migration `0003_collector_findingtype_collectorinstance_and_more`
- Independent M0 stubs:
  - `/healthz`
  - 10 runbook placeholder files.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` passed.

**Process correction:** This build WIP was created before the module-doc
delegation rule was added to `DEVELOPMENT.md`. Future Operations slices must
checkpoint here and in `operations/BUILD_BLUEPRINT.md` before edits.

**Pending:** M0.6 observations/dead-letter/current-state schema and refresh
function. Requires approval before implementation.
