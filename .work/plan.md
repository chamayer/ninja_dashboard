# Active root work plan

Track: **Observation model redesign — content-hashed current + SCD-2 history**

## Status

- Discovery complete. ADR-0007 is v3 and Proposed. The root plan now also
  incorporates the round-2 corrections; the ADR itself still needs to be
  revised to match before acceptance.
- Schema slice started: `EntityObservationCurrent` and
  `EntityObservationHistory` models plus migrations 0063/0064 are present;
  writer dual-write and reader migration remain pending.
- `python manage.py check` passes. No database migration has been applied.

## Goal

Replace the append-per-cycle `operations.entity_observations` table with
two purpose-built tables — `entity_observation_current` (one row per
canonical identity tuple, upserted every cycle, with active/withdrawn
semantics) and `entity_observation_history` (SCD-2 with explicit effective
intervals, appended on material or presence-state transitions) — so current-
state reads become PK lookups and history reads scan only real change
events.

## Scope

- **In:** ADR-0007 v3; observation identity contract; writer primitive
  extraction; new schema (tables, indexes, RLS grants, partial unique
  constraints); absence / snapshot-run reconciliation; dual-write
  phase; reader migration across ~20 sites in ingest + operations;
  matview rebuilds; `identity_candidates` FK migration; `queue_registry`
  update; cutover and legacy-table archival; retention policy on
  `_history`; DESIGN.md + `docs/architecture.md` updates in the same
  track.
- **Out:** Ninja `raw_data={}` fidelity fix — ships naturally once
  `_current` lands (raw_data on `_current` is heartbeat-refreshed by
  design); connector contract changes; Metabase side (deprecated).

## Files involved

**ADR + planning:**
- `operations/docs/decisions/0007-observation-model-content-hashed-current-plus-history.md` — decision record v3 (Proposed).
- `operations/.work/plan.md` — pointer to this cross-service plan.

**Writer primitive (Slice 1):**
- `ingest/observations.py` (new) — batch-oriented
  `write_observations(cur, obs_rows)` helper plus pure per-row identity/hash
  normalization. Preserve today's bulk-write shape in S1.
- `ingest/core/devices.py` — call primitive from `_write_ninja_observations`.
- `ingest/source_observations.py` — call primitive from `run_source_observations`.
- `ingest/inventory/software.py` — call primitive from software writer.

**Identity contract + hash policy (Gate 0, before schema):**
- `ingest/observations.py` — one physical identity tuple shared by all
  entity families, with family-specific validation; material-fields policy
  per family; `hash_algorithm_version`; fail-closed handling for undeclared
  entity types. Central config.

**Schema (Slice 2):**
- `operations/apps/core/migrations/NNNN_entity_observation_current.py` —
  new table with the uniform key `(tenant_id, source_binding_id,
  entity_type, parent_source_key, entity_key)`, where
  `parent_source_key TEXT NOT NULL DEFAULT ''` for top-level entities;
  `active`, `withdrawn_at`, `snapshot_scope`, `last_snapshot_run_id`,
  `last_snapshot_at`, `last_received_at`, `raw_hash`, `hash_algorithm_version`;
  bounded natural
  key checks; tenant-consistent references; secondary indexes; RLS grants;
  update-heavy table storage/autovacuum settings.
- `operations/apps/core/migrations/NNNN_entity_observation_history.py` —
  new SCD-2 table using the same uniform identity tuple, with
  `effective_from`, `effective_to`, `last_seen_at`, `material_data JSONB`;
  full `raw_data` is excluded from history by policy. Partial unique index
  enforcing at most one open version per tuple; retention-friendly index
  on `effective_to`.
- `operations/apps/core/models.py` — new Django models mirroring the tables.
- `operations/apps/core/migrations/NNNN_observation_snapshot_runs.py` —
  durable scope-level run ledger with tenant, binding, scope, run id,
  monotonic snapshot boundary, completeness/status, expected/written/failed
  counts, supersession rule, and reconciliation outcome.
- `ingest/observation_runs.py` (new) — starts/finalizes snapshot scopes and
  atomically gates reconciliation on the latest successful complete run.

**Reader migration (Slice 3) — updated inventory:**
- `ingest/identity/resolver.py` — 9 sites: :55 (unresolved-resolution),
  :241, :274, :581 (unresolved grouped first/latest), :920, :952, :983,
  :1133, :1358 (30-day junk-MAC). Most → `_current` (with
  `active=true`); the 30-day interval-overlap scan → `_history`.
- `ingest/identity/fast_path.py:173` — identity-conflict NOT EXISTS → `_current WHERE active=true`.
- `ingest/identity/client_resolver.py:89, :532` — org resolution → `_current`.
  Also migrate direct legacy references at `:243, :256, :529` (device/client
  linkage reads and updates); these are part of the runtime writer/reader
  inventory, not historical-only code.
- `ingest/evaluator.py` — 5 SQL statements: :236/:240 (one latest-state
  query → `_current WHERE active=true` plus freshness predicate),
  :351/:355 (one COUNT query → current entity count from `_current WHERE
  active=true` plus freshness predicate), :407/:410 (one latest-state
  query → `_current WHERE active=true` plus freshness predicate), :472/:475
  (recent-online query → `_history`, backed by material online/offline
  transitions), :768 (current-state → `_current`).
- `operations/apps/core/views.py:1235` — Raw tab (0.80.0 code) → `_current`; removes the Ninja fallback join (raw_data is populated by design).
- `operations/apps/core/views.py:4094, :4113, :4147` — client-merge preview → `_current` for latest state, `_history` for aggregates.
  `operations/apps/core/views.py:4249, :4264` — client-merge execution updates
  observation device/client linkage; rewrite against `_current` (and preserve
  the approved resolver/merge semantics). `:4710-4712` — tenant maintenance
  update; migrate or explicitly retire before legacy-table rename.
- `operations/apps/core/migrations/0011_software_staleness.py:55, :91` — persistent function reading old table. Rewrite to read `_current`; NOT EXISTS becomes `WHERE active=false OR withdrawn_at IS NOT NULL`.
- Derived objects: rebuild materialized views
  `device_agent_presence_current` and `source_health_current` against
  `_current`; rewrite the persistent
  `refresh_software_installations_current()` function that maintains the
  `software_installations_current` table. Consider view simplification only
  behind Gate 2.

**Cross-schema dependencies (Slice 4):**
- `operations/apps/core/migrations/0019_identity_candidates.py` — FK `observation_id → entity_observations`. Must migrate to the new schema or the row is retired before old table can be dropped. Per project memory (identity_candidates retirement is in backlog), preferred path is retire during this cutover.
- `operations/apps/core/migrations/0014_platform_tables.py` — `queue_registry` row references literal `operations.entity_observations`. Update in same migration that renames the old table.
- Fresh-install migration SQL also names the legacy table in `0016`, `0018`,
  `0021`, `0025`, `0036`, `0044`, `0060`, and `0061`. Before cutover, classify
  each reference as (a) rewritten to the new tables in a forward migration,
  (b) intentionally preserved for compatibility while the legacy table exists,
  or (c) historical-only and left untouched. Run a fresh-database migration
  rehearsal; no migration may assume the legacy table has already been
  renamed or dropped.

**Docs (Slice 4):**
- `operations/DESIGN.md` line 16 — remove "No parallel observation tables"; document the two-table split.
- `operations/docs/architecture.md` — new section on observation identity contract, absence semantics, and the current/history split.
- Classify remaining references in `DESIGN.md`, `BLUEPRINT.md`, `TODO.md`, and
  `SESSIONS.md` as normative (update), migration/history (retain with a clear
  historical marker), or obsolete (remove only with explicit approval). The
  final grep is a reviewed inventory, not a requirement that every historical
  changelog line be rewritten.

**Backfill tooling (Slice 2b):**
- `ingest/backfill_observations.py` (new) — resumable, idempotent, bounded-batch
  current/history backfill with durable checkpoints and dry-run reporting;
  not a data migration executed inside Django's migration transaction.

## Gates (require greenlight before executing)

- **Gate 0 — Observation identity contract.** Per-entity-type key
  validation locked around one uniform physical tuple before schema migration
  is written. Software requires a non-empty source-native
  `parent_source_key`; top-level families use `parent_source_key=''`.
  Gate 0 inventories observed key byte lengths and locks database-enforced
  individual/combined `octet_length` limits that fit PostgreSQL B-tree index
  tuple limits. Oversized or undeclared identities fail closed to the existing
  dead-letter path. This must not be redecided during S2.
- **Gate 1 — Migration SQL.** Full column shape for both tables,
  snapshot-run ledger, material-fields policy per family, query-derived index
  strategy, tenant-consistent foreign-key strategy, RLS `USING`/`WITH CHECK`,
  update-heavy storage/autovacuum settings, retention default for `_history`
  (proposed 90 days), and migration transaction/lock strategy — all shown for
  review before the migration is written. Also lock source-binding
  `PROTECT`/soft-delete behavior, history material-data shape, received-time
  skew policy, raw-data grants/redaction, and tenant-safe derived-view access.
- **Gate 2 — Matview simplification.** Each matview removal or
  reshape needs its own justification. Not automatic.
- **Gate 3 — `identity_candidates` decision.** Migrate the FK or
  retire the table. Per backlog, retirement is preferred. Confirmed
  before S4.
- **Gate 4 — external mutations.** Commit, push, deployment, legacy-table
  rename/drop, and `identity_candidates` retirement each require the
  applicable separate explicit authorization. ADR or slice acceptance does
  not grant those permissions.
- **Gate 5 — operational readiness.** Writer throughput/WAL/dead-tuple
  benchmarks, resumable-backfill rehearsal, snapshot-scope failure accounting,
  RLS/tenant-isolation tests, and an expand/contract rollback drill must pass
  before S4.

## Steps (slice-by-slice)

### S1 — Extract writer primitive (behavior-preserving)

- [ ] Add `ingest/observations.py::write_observations(cur, obs_rows)` —
  initially delegates the complete batch to today's `db.insert_ignore` on
  `entity_observations`. No dedupe logic yet; pure refactor that preserves
  `executemany()` behavior.
- [ ] Point all three writer sites at the new helper.
- [ ] Validation: focused ingest run against dev DB, row counts
  unchanged, `entity_observations` still populated as before.
- [ ] Present the validated Slice 1 diff for review. Commit and push only
  after their separate explicit approvals.

**Reviewer-cleared as low risk. Can open in parallel with ADR round 2.**

### S2 — Schema + dual-write (behind Gates 0 and 1)

- [ ] Lock the uniform identity tuple in `ingest/observations.py`; enforce
  per-family requirements (`software.parent_source_key` required,
  top-level parent key empty) and fail closed for undeclared families,
  including an explicit policy for today's `unknown` entity type.
- [ ] Lock material-fields policy per family + `hash_algorithm_version = 1`:
  - `vm.*`: `power_state` and `last_boot_time_at` are material.
  - Agent/tracking families: `is_online` transitions are material because
    the evaluator asks whether a source saw a device online recently;
    heartbeat/contact timestamps remain non-material.
  - Software uses the current canonical key `location` (not
    `install_path`).
  - `platform_group_id` and `is_dup` receive explicit policy; `is_dup` is
    material, and group changes remain auditable identity/client-resolution
    evidence.
  - `org.device_count` remains non-material in v1.
- [ ] Lock timestamp provenance: persist `_current.last_received_at` and
  immutable history-version `received_at` separately
  from source/snapshot `observed_at`; reject or dead-letter observations beyond
  the approved future-skew bound and use the run boundary for withdrawal.
- [ ] Draft `_current` migration: one uniform composite PK, `active`,
  `withdrawn_at`, `snapshot_scope`, `last_snapshot_run_id`,
  `last_snapshot_at`, `last_received_at`, `raw_hash`, `hash_algorithm_version`, volatile refresh
  columns, bounded natural-key checks, tenant-consistent references,
  secondary indexes on `(tenant_id, device_id)` and
  `(tenant_id, client_id)`, RLS `USING`/`WITH CHECK`, explicit grants, and
  reviewed `fillfactor`/autovacuum settings for an update-heavy table.
- [ ] Draft `_history` migration: `effective_from`, `effective_to`,
  `last_seen_at`, `material_data`, `material_hash`, `hash_algorithm_version`, partial
  unique index enforcing at most one open version per tuple, plus indexes
  derived from the frozen tenant/device/binding/window reader shapes and
  batched-retention predicate.
- [ ] Draft `observation_snapshot_runs` migration and model. Run completion
  and reconciliation outcome are durable state, not inferred from logs.
- [ ] Make source bindings and collector/source references retention-safe:
  observation rows use `PROTECT` or an explicit detach/archive path; deleting
  a source configuration cannot delete observation evidence.
- [ ] Propose all schema SQL, storage settings, grants, and forward/reverse
  lock behavior for review (Gate 1). Schema expansion must be independently
  deployable before any writer references the new objects.
- [ ] Extend writer primitive to dual-write:
  - Continues writing to old `entity_observations` (source of truth).
  - Uses a set-based batch/staging operation for `_current` comparison and
    history close/open; does not replace today's `executemany()` path with
    several client/server round trips and savepoints per entity.
  - Upserts `_current` with heartbeat refresh + out-of-order guard +
    resolved-ID preservation. Replaces `raw_data` only when `raw_hash`
    changes; measures canonical JSON, TOAST, WAL, and dead-tuple churn.
  - Stores only the material projection in `_history`; never copies raw
    payloads there without a separately approved data-governance exception.
  - Rejects an older observation before material comparison or any history
    close/open operation.
  - On material hash change: transactional close/open on `_history`.
  - Wraps each new-table batch in a database savepoint. On failure, rolls back
    the complete `_current` + `_history` batch to that savepoint, preserves
    the legacy write, increments attempted/succeeded/failed counters, and
    marks the snapshot scope's new path incomplete. Current and history never
    diverge partially.
- [ ] Add explicit dual-write health gates:
  - Any failed new-table batch makes that snapshot scope unhealthy and skips
    reconciliation; failed rows can never masquerade as source absence.
  - Legacy collection success and new-path health are reported separately.
  - Cutover requires zero new-path failures across the full soak plus matched
    expected/written identity counts for every complete scope.
- [ ] Add post-snapshot reconciliation pass for complete-snapshot
  sources (Ninja devices, S1 devices, LMI hosts, Ninja fleet software).
  Gate 1 must verify each claimed completeness contract against its connector;
  a paginated fetch is not treated as complete unless all pages succeeded.
  Reconciliation runs only after a successful complete snapshot and is
  scoped by `(tenant_id, source_binding_id, snapshot_scope)` so one stream
  cannot withdraw sibling entity families on the same binding.
  - Persist a monotonic snapshot boundary (`last_snapshot_at`) separately
    from wall-clock completion time. `observation_snapshot_runs` permits
    reconciliation only for the latest successful, complete, new-path-healthy
    run.
    A late older run skips reconciliation and cannot withdraw rows written by
    a newer snapshot.
  - Withdrawal marks unseen `_current` rows inactive, records the successful
    run boundary as `withdrawn_at`, and closes the open history interval.
  - Reactivation clears `withdrawn_at` and opens a new history interval even
    when the material hash matches the pre-withdrawal state.
  - Reconciliation and run-ledger completion commit atomically. Partial-
    snapshot sources never reconcile absence.
- [ ] Capture pre-change baselines for cycle duration, rows/sec, WAL bytes,
  table/TOAST bytes, dead tuples, autovacuum activity, lock waits, and errors.
  Gate 1 approves quantitative regression limits relative to collection
  cadence and available capacity; no unmeasured percentage is assumed.
- [ ] Run dual-write for long enough that every enabled snapshot scope has
  completed multiple successful cycles, including its least-frequent
  schedule. Verify:
  - `_current` row count is near the expected active plus withdrawn identity
    count; repeated cycles create no growth. Any growth is attributable to a
    newly seen identity tuple, not heartbeat amplification.
  - `_history` growth stays within the measured, Gate-1-approved change-event
    budget; the initial 10K rows/day estimate is a hypothesis, not a release
    criterion.
  - Material-hash distribution: most tuples have exactly one open
    hash, some have 2-3 closed historicals.
  - Withdrawn rows appear for devices genuinely gone from source.
  - No `_history` version has `effective_to = effective_from` (would
    indicate mishandled churn); material_data reconstructs every history
    reader's required fields; future-skew and received/observed-time tests
    pass.
- Measured cycle duration, WAL/TOAST churn, dead tuples, autovacuum, lock
  waits, and storage remain inside the approved Gate 1 limits. Tune batch
  size, `fillfactor`, and autovacuum before proceeding if they do not.

### S2b — Seed current state and bootstrap history (before reader migration)

- [ ] Seed `_current` from the latest legacy row per uniform identity tuple.
  Derive software `parent_source_key` from the source-native device link.
- [ ] Do not expose seeded rows as authoritative active state until every
  complete-snapshot scope has completed one successful reconciliation.
  Partial-snapshot rows retain explicit unknown/recency semantics rather than
  claiming verified presence.
- [ ] Backfill 30 days of material history by ordering legacy rows per
  identity tuple and run-length segmenting consecutive equal hashes; do not
  globally group recurring A→B→A states. Construct ordered, non-overlapping
  intervals. Online/offline transitions participate for families whose reader
  semantics require them.
- [ ] Validate interval-overlap behavior for the 30-day junk-MAC query; an
  interval counts when it overlaps the requested window, not only when its
  `effective_from` falls inside it.
- [ ] Rehearse the backfill with bounded batches, checkpoints, restart after
  interruption, disk/WAL headroom checks, lock/statement timeouts, and a
  post-load `ANALYZE`; record the shadow comparison before exposure.
- [ ] Complete S2b before any S3 reader is repointed.

### S3 — Migrate readers

- [ ] Reader-by-reader sweep using the frozen inventory above. For
  each site:
  - Current-state DISTINCT ON → `_current` (with `active=true`).
  - Current-state queries with 2-7 day cutoffs → `_current` plus the same
    `last_seen_at`/`observed_at` freshness predicate; a cutoff does not by
    itself make a query historical.
  - `active=true` is authoritative presence only for successfully reconciled
    complete-snapshot scopes. Presence readers covering partial-snapshot
    scopes must also apply an explicit freshness rule; `active` there means
    "not known withdrawn," not proof of present state.
  - True windowed history → `_history` using interval-overlap semantics on
    `effective_from`/`effective_to`.
  - EXISTS-as-presence → `_current WHERE active=true`.
  - COUNT(*) → redefine as current-count from `_current WHERE
    entity_type=? AND active=true`. Semantic change documented in
    the commit.
  - Software staleness function (migration 0011) → `WHERE active=false
    OR withdrawn_at IS NOT NULL`.
- [ ] Ship reader migrations as multiple small commits, one subsystem
  at a time (resolver, evaluator, views, software-staleness function).
- [ ] Rebuild matviews (Gate 2 per matview). Some may become plain
  views or be removed if `_current` is fast enough.
- [ ] For every derived view/matview, document role grants, tenant filtering,
  security-barrier wrapper requirements, and cross-tenant tests; table RLS does
  not protect direct reads from materialized views.
- [ ] End-to-end run of identity resolver + evaluator against dev DB.
  Confirm findings match old vs new within noise.
- [ ] Raw-tab spot-check: 0.80.0 code repointed at `_current`, Ninja
  fallback code removed. Verify common-field matrix + per-source
  specifics render identically.

### S4 — Cutover (behind Gates 3, 4, and 5)

- [ ] `identity_candidates` decision executed (retire or migrate FK).
- [ ] If retired, preserve each candidate's observation evidence by replacing
  the old FK/reference with a stable current/history tuple or snapshot-run
  evidence reference before removing the side table.
- [ ] Update `queue_registry` row that names `entity_observations`.
- [ ] Update DESIGN.md + `docs/architecture.md`.
- [ ] Document raw-data governance: allowed roles, redaction boundary, no raw
  payloads in logs/dead letters beyond the approved envelope policy, tenant
  offboarding/deletion procedure, and explicit exclusion of raw history.
- [ ] After separate deployment/cutover approval, stop writing to old
  `entity_observations`.
- [ ] Execute the expand/contract rollout in this order: schema exists;
  dual-write healthy; current/history seeded; readers deployed compatibly;
  legacy writes stopped; legacy insert/update counters remain zero for the
  observation window; then rename. Keep the rollback path deployable until
  legacy retirement is separately approved.
- [ ] After separate destructive approval, rename `entity_observations` →
  `entity_observations_legacy`
  (one-cycle safety net).
- [ ] Run the required rollback-observation window. Verify zero legacy
  inserts/updates and zero new legacy reads using pre-cutover baselines plus
  `pg_stat_statements`/query telemetry; do not treat cumulative
  `pg_stat_user_tables.seq_scan` alone as evidence.
- [ ] After a further separate destructive approval, drop
  `entity_observations_legacy` after at least 24 hours clean.
- [ ] Add monitored, resumable retention on `_history`: delete bounded
  batches using the tenant/effective-to index, only where `effective_to IS
  NOT NULL AND effective_to < NOW() - INTERVAL '90 days'`; never touch the
  open version. Vacuum/bloat behavior and retry/alert semantics are part of
  the nightly host-cron or ingest-scheduler decision at S4.

## Decisions

- **Two tables, not one.** Physical split matches reader usage.
- **One physical identity tuple for every family.** Software requires a
  source-native `parent_source_key`; top-level entities store the empty
  string. Family policy validates the shared shape rather than changing the
  database key.
- **Absence semantics on `_current`** (`active` + `withdrawn_at` +
  `last_snapshot_run_id`) rather than inferring absence from missing
  rows. First-class withdrawal for verified complete-snapshot scopes; partial
  scopes remain last-known state and require reader freshness semantics.
- **Heartbeat refreshes volatile state on `_current` every write.**
  `_history` changes only for material transitions or presence lifecycle
  boundaries (withdrawal/reactivation).
- **Presence transitions participate in history.** Withdrawal closes the
  open version; reactivation opens a new one even when content is unchanged;
  online/offline is material where a reader needs recent status history.
- **Per-entity-type material policy** with `hash_algorithm_version`.
  Not per-connector overrides.
- **Writer primitive extracted first** — removes the three-place
  adjacency that let the timestamp-in-hash mistake go unchallenged.
- **No stopgap retention.** Real fix only. Accepts ~2-4 weeks of
  continued growth (~10-15 GB) during redesign.
- **`identity_candidates` retirement folded into S4.** Per backlog
  preference; avoids a dead FK dragging `_legacy` around.

## Reader inventory (frozen — round 2)

**A. Current-state → `_current`, with reader-specific activity semantics:**
- Presence/identity readers use `active=true` and retain existing freshness
  predicates: `ingest/identity/resolver.py:55, :274, :581, :920, :952,
  :983, :1133`; `ingest/identity/client_resolver.py:89, :532`;
  `ingest/evaluator.py:236/:240, :407/:410, :768`.
- `operations/apps/core/views.py:1235` (Raw tab, 0.80.0) includes inactive
  last-known rows and exposes `active` / `withdrawn_at` so source withdrawal
  remains visible rather than silently removing a source column.
- `operations/apps/core/views.py:4147` (client-merge preview) uses active rows;
  first/last aggregates follow section D.
- `device_agent_presence_current` uses active rows.
- `source_health_current` considers active and inactive latest rows for
  last-observed timestamps and continues to union run-log platforms, so a
  fully withdrawn or failed source does not disappear from health reporting.
- Persistent software refresh function/table:
  `refresh_software_installations_current()` / `software_installations_current`

**B. True windowed history → `_history` with interval-overlap filter:**
- `ingest/evaluator.py:472/:475` (recent-online; online transitions material)
- `ingest/identity/resolver.py:1358` (30-day junk-MAC)

**C. EXISTS-as-presence → `_current WHERE active=true`:**
- `ingest/identity/resolver.py:241`
- `ingest/identity/fast_path.py:173`
- `operations/apps/core/migrations/0011:91` — software staleness NOT EXISTS
  → `WHERE active=false OR withdrawn_at IS NOT NULL`

**D. Aggregate first/last observed_at → derived from `_current` or `_history`:**
- `operations/apps/core/views.py:4094, :4113` (client-merge queue MIN/MAX/COUNT)

**E. Reclassified — COUNT(*) → fresh current entity count (semantic change):**
- `ingest/evaluator.py:351/:355` — `_evaluate_unknown_entities`; retain the
  two-day freshness condition. Documented in the commit.

**Writes to migrate to primitive:**
- `ingest/core/devices.py::_write_ninja_observations`
- `ingest/source_observations.py::run_source_observations`
- `ingest/inventory/software.py`
- Resolver / client-resolver post-hoc UPDATE `device_id` / `client_id` → `_current` (identity tuple key propagates).
- Merge paths (`views.py::_merge_devices`, `_merge_clients`) → `_current`.

## Validation plan

- **S1:** row counts unchanged across an ingest cycle before/after
  primitive extraction.
- **S2:** dual-write cycle produces `_current` row count within
  expected range; `_history` growth stays within the Gate-1-approved
  change-event budget; material-hash
  distribution shows expected clustering; withdrawn rows appear when
  devices leave source; no `effective_to = effective_from` rows; active rows
  have exactly one open history version and withdrawn rows have none;
  out-of-order observations cause no current or history mutation; injected
  new-table failures roll back to the savepoint while preserving the legacy
  write; an older complete run finishing after a newer one skips
  reconciliation and withdraws nothing.
- **S2b:** seeded current count matches the uniform identity tuple count;
  complete scopes reconcile before exposure; 30-day history has ordered,
  non-overlapping intervals; withdrawal/reactivation tests pass for unchanged
  and changed content; an A→B→A legacy sequence produces three intervals.
- **S3:** identity-resolver output identical (findings match by
  tuple + severity within noise); matview refresh times before/after;
  Raw tab spot-check; software-staleness function marks the same
  installs stale/unstale; raw-data access and matview cross-tenant tests pass.
- **S4:** post-rename, zero legacy inserts/updates and zero new legacy reads
  against pre-cutover telemetry baselines for the approved observation
  window; rollback drill remains viable; `identity_candidates` decision
  executed; source-delete and identity-evidence preservation tests pass.

## Estimated effort

| Slice | v1 estimate | v3 estimate |
|---|---|---|
| S1 writer primitive | 1 day | 1 day (unchanged) |
| S2 schema + dual-write | 2-3 days | 5-7 days (identity contract, batch writer, run ledger, health gates, absence semantics, SCD-2 correctness, out-of-order guard, reconciliation pass, performance baselines) |
| S2b seed + 30-day backfill | — | 2-4 days (resumable rehearsal and shadow comparison; must precede reader migration) |
| S3 reader migration | 2-3 days | 3-4 days (more readers, absence-filter propagation, matview justification) |
| S4 cutover | 1 day | 3 days (expand/contract rollout, telemetry window, rollback drill, identity_candidates + queue_registry + docs) |
| **Total** | **~1 week** | **~3-4 weeks** |

## Current checkpoint

- Discovery complete. Numbers: 4.7 GB, 3.0M rows, 300K rows/day, no
  retention (n_tup_del=0), no pg_cron, not partitioned.
- Reader inventory round 2 captured above. It includes the previously omitted
  resolver sites, persistent software refresh function,
  `identity_candidates` FK, queue-registry literal, evaluator COUNT semantic
  change, statement-level line grouping, current-versus-history correction,
  and reader-specific active/freshness behavior.
- Writer inventory: three sites, all append-per-cycle, timestamp-in-
  hash.
- ADR-0007 v3 remains Proposed. Root plan revised after reviewer round 2 and
  the security/data-governance review to
  resolve the uniform physical key, withdrawal/reactivation history,
  reconciliation scope, reader semantics, backfill ordering, savepoint, and
  authorization-gate findings. The plan then received an SRE/DBA pass adding
  batch/WAL controls, snapshot-scope health gates, resumable backfill,
  expand/contract rollback, and monitored retention, followed by a
  security/data-governance pass adding material history payloads,
  timestamp provenance, source-retention safety, raw-data governance,
  matview tenant boundaries, and identity-evidence preservation.
- Awaiting ADR revision and review; Slice 1 implementation also awaits explicit
  authorization. Commit and push remain separately gated.

## Next action

- Perform another architecture review of ADR-0007 v3 and the synchronized
  plan.
- On explicit implementation authorization, open Slice 1 as the first
  executable change. Seek separate approval before commit or push.
