# 0007 — Observation model: content-hashed current + SCD-2 history

Status: Proposed (v3 — revised after review 2026-07-21)
Date: 2026-07-21 (v1 drafted); 2026-07-21 (v2/v3 revised)

## Revision history

- **v3 (2026-07-21).** Added material history payloads, received-time
  provenance/skew handling, source-retention safety, raw-data governance,
  tenant-safe matview boundaries, and identity-evidence preservation.
- **v2 (2026-07-21).** Rewritten to address blocking review findings:
  (1) observation identity contract added — v1's proposed `_current` PK
  collapsed software installations across devices; (2) absence /
  tombstone semantics added — v1's `_current` was "latest observation
  ever," not "present state," which broke software-staleness NOT EXISTS
  and any EXISTS-as-presence claim; (3) heartbeat semantics corrected —
  v1 only bumped `last_seen_at` on unchanged content, freezing volatile
  fields (`is_online`, `last_contact`) on `_current`; (4) SCD-2 interval
  semantics corrected — v1 conflated "last confirmed" with "effective
  boundary." Material-hash policy moved from a single global blocklist
  to per-entity-type policy with an explicit `hash_algorithm_version`.
- v1 (2026-07-21). Initial draft. Superseded by v2/v3 in place.

## Context

`operations.entity_observations` is written append-per-cycle by every source
connector (Ninja / SentinelOne / LogMeIn / ScreenConnect / software / orgs).
The current write shape hashes `entity_key + snapshot_at.isoformat()` into
`observation_hash`, so every row is unique by construction. The conflict key
`(tenant_id, collector_instance_id, batch_id, observation_hash)` never fires
— it exists as a defensive re-run guard, not a dedupe mechanism.

Discovery numbers (2026-07-21):

- Total size: **4.7 GB** / 3.0M rows / 300K rows per day / ~500 MB/day growth.
- `n_tup_del = 0` since stats reset; no `pg_cron` extension installed; no
  retention job of any kind. Growth is unbounded.
- Ninja alone: 108K rows/day at 24 cycles per day for ~4,500 devices.

Reader survey shows ~80% of read sites want current-state
(`DISTINCT ON … ORDER BY observed_at DESC`), ~15% want a bounded time
window (2-30 days), ~5% are `EXISTS` probes. **No reader needs
cardinality of writes over time.** The append-per-cycle pattern serves
none of these readers well: current-state pays `DISTINCT ON` cost
forever, windowed queries scan far more rows than they need, storage
cost is unbounded.

Related decisions:

- ADR-0001 established the shared observation pipeline as the connector
  contract. Unchanged by this decision.
- ADR-0003 defined the four-layer split (raw / observation / canonical /
  derived). This decision splits the observation layer itself into two
  physical tables mapping to its two jobs.
- DESIGN.md line 16 currently prohibits parallel observation tables.
  This ADR supersedes that rule; DESIGN.md and `docs/architecture.md`
  are updated in the same track.

## Options considered

- **A. Explicit retention job (stopgap).** Nightly `DELETE` keeping the
  last N days. Bounds storage cheaply. Does not fix the underlying
  design flaw — every kept row is still mostly duplicate — and pushes
  the "what is history worth keeping?" question onto an arbitrary
  window with no semantic meaning. Rejected as permanent answer.
- **B. In-place content-hash + heartbeat.** Change `observation_hash` to
  hash material fields of `canonical_data`, single table, UPSERT on
  hash bumping `last_seen_at` on repeat. Preserves single-table
  simplicity. Rejected: readers still `DISTINCT ON` for current state;
  table still conflates current-state and change-log jobs even though
  ADR-0003 separated them at the layer level; no place to attach
  absence semantics cleanly.
- **C. Split into `entity_observation_current` + append-on-material-
  change `entity_observation_history`.** Selected.

## Decision

### Two tables

1. **`operations.entity_observation_current`** — one row per canonical
   identity tuple (see identity contract below). `UPSERT`ed by every
   source cycle. Bounded by distinct active and retained identity tuples
   (no per-cycle row growth; approximately 50K today). Always fresh, direct
   lookup, source of truth for "what does source X say about entity Y
   right now."
2. **`operations.entity_observation_history`** — SCD-2. One row per
   distinct material state of the same tuple, with explicit effective
   interval and a `material_data` JSONB projection containing the fields
   required by historical readers. Full `raw_data` is not copied into
   history. Written when material or presence state changes. Retention lives
   here.

### Observation identity contract (uniform physical key)

Both tables use one physical identity tuple:
`(tenant_id, source_binding_id, entity_type, parent_source_key, entity_key)`.
Top-level entities store `parent_source_key = ''`; child entities require a
source-native parent key. The writer primitive validates family rules without
changing the database key.

- **`agent.*`, `vm.host`, `vm.guest`, `network.device`, `monitor.target`,
  `org`** — parent key is empty and
  `(tenant_id, source_binding_id, entity_type, '', entity_key)` is used.
  `entity_key` is the source's native id (Ninja device id, S1 uuid,
  LMI host id, org id), unique within its binding.
- **`software`** — `(tenant_id, source_binding_id, entity_type,
  parent_source_key, entity_key)`. `parent_source_key` is the source's
  own device id (Ninja `deviceId`), NOT the operations `device_id`
  (which is nullable and post-hoc mutable). `entity_key` is the
  normalized software name.
- **Future child-entity sources** must declare their parent scope in
  the writer primitive. Adding a new entity family is a code change
  in one file, not a schema migration.

### Absence / tombstone semantics on `_current`

Every `_current` row carries:

- `active BOOLEAN NOT NULL DEFAULT true`
- `withdrawn_at TIMESTAMPTZ NULL`
- `last_snapshot_run_id UUID NOT NULL` — generation id per complete-
  snapshot run
- `last_received_at TIMESTAMPTZ NOT NULL` — receipt time of the latest
  accepted observation, distinct from source/snapshot observation time.

After each complete-snapshot ingest cycle for a given source, a
reconciliation pass marks any `_current` row belonging to that source
  whose `last_snapshot_run_id` doesn't match the current run as
  `active = false`, with `withdrawn_at` set to that run's monotonic
  snapshot boundary. Applies to sources that
guarantee complete snapshots per cycle: Ninja devices, S1 devices,
LMI hosts, Ninja fleet software queries. Partial-snapshot sources
skip reconciliation.

Presence-style probes (former `EXISTS` against `entity_observations`)
must filter `WHERE active = true`. Software staleness detection moves
from `NOT EXISTS` in `apps/core/migrations/0011_software_staleness.py`
to `WHERE active = false OR withdrawn_at IS NOT NULL`.

### Heartbeat semantics

Every write to `_current` (regardless of material hash change):

- Refreshes: `observed_at`, `last_seen_at`, `raw_data`, complete
  `canonical_data` (volatile fields included), `batch_id`,
  `collector_version`, `schema_version`, `last_snapshot_run_id`.
- Does not overwrite `device_id` / `client_id` with NULL if the current
  row has a resolved value — post-hoc resolver / merge writes take
  precedence over connector NULLs.
- Out-of-order guard: `UPDATE ... WHERE _current.observed_at <=
  EXCLUDED.observed_at`. Older snapshots silently lose the race so
  clock skew or delayed workers cannot poison newer state.

The history version-opening event stores immutable `received_at`, the ingest
receipt time, separately from source/snapshot `observed_at`; `_current` stores
the latest receipt as `last_received_at`. Observations beyond the
approved future-skew bound are rejected or dead-lettered. Withdrawal uses the
successful snapshot-run boundary rather than an unqualified wall-clock
`NOW()`.

`_history` writes are conditional on material or presence-state change.

### Material-hash policy (per-entity-type family)

Central config in `ingest/observations.py`. `hash_algorithm_version`
column on both `_current` and `_history` — bumping the version triggers
controlled rehash of affected rows.

Initial policy (v1 of the algorithm):

- **`agent.*`** — material: `hostname`, `serial_number`, `os_name`,
  `os_family`, `os_version`, `macs`, `domain`, `entity_type`,
  `platform`, `device_role`. Non-material: `last_seen_at`, `is_online`,
  `last_boot_time_at` (per this family; see next bullet).
- **`vm.host`, `vm.guest`** — as above plus `power_state`, `vm_uuid`,
  `parent_ninja_id`. `power_state` is material for VM entities per the
  authoritative-liveness rule in `apps/core/migrations/0036_presence_power_state.py`.
- **`network.device`, `monitor.target`** — as `agent.*` plus source-
  specific identifiers where present.
- **`software`** — material: `publisher`, `version`, `install_path`,
  `install_date`. Non-material: `last_observed_at`.
- **`org`** — material: normalized name. `device_count` explicitly
  non-material in v1 (partial-snapshot noise); revisit if operators
  need count-change history.

Rules the policy must follow:

- Only *normalized canonical field names* enter the material set. No
  raw source-side aliases (`last_contact`, `hostStateChangeDate`,
  `lastActive`) — including future aliases silently discards renamed
  fields.
- One shared policy per entity-type family, defined centrally. No
  per-connector overrides.

### SCD-2 interval semantics

`_history` columns:

- `effective_from TIMESTAMPTZ NOT NULL` — the observation time at
  which this material state was first observed (opens the version).
- `effective_to TIMESTAMPTZ NULL` — the observation time at which
  the *next* material state took over. NULL for the currently open
  version.
- `last_seen_at TIMESTAMPTZ NOT NULL` — the last observation
  confirming this state. On close, inherited from the prior
  `_current.last_seen_at` (which was heartbeat-refreshed until the
  material change).
- `material_data JSONB NOT NULL` — canonical material projection needed by
  historical readers, such as `macs` and online-state transitions. Raw source
  payloads remain current-only unless a separately approved data-governance
  exception exists.

Transaction shape on material change:

1. `SELECT ... FOR UPDATE` on `_current` for the identity tuple.
2. `UPDATE entity_observation_history SET effective_to = %new_observed_at%,
   last_seen_at = %prior_current_last_seen_at% WHERE identity tuple AND
   effective_to IS NULL`.
3. `INSERT INTO entity_observation_history (...effective_from = %new_observed_at%,
   effective_to = NULL, last_seen_at = %new_observed_at%)`.
4. `UPDATE entity_observation_current SET ...` (new material + heartbeat
   refresh).

Constraint:

- Partial unique index on `entity_observation_history (tenant_id,
  source_binding_id, entity_type, parent_source_key, entity_key)
  WHERE effective_to IS NULL` — enforces at most one open version per
  tuple. Active rows must have one open version; withdrawn rows have none.

## Rationale

- **Reader ergonomics.** ~80% of the reader inventory becomes a direct
  PK lookup instead of `DISTINCT ON`. Matviews
  (`device_agent_presence_current`, `software_installations_current`,
  `source_health_current`) collapse to plain SELECT or disappear.
- **Storage.** Estimated ~100x reduction in write volume for the
  identity signal (from 300K rows/day on the aggregate table to
  ~3-10K rows/day of actual material change on `_history`, plus a
  steady ~50K rows on `_current`). Retention on `_history` becomes a
  real question with a real answer.
- **Semantic honesty.** The single `entity_observations` table was
  doing state-store and change-log jobs badly. Splitting names them.
- **Enables Ninja `raw_data` fidelity fix without regret.** Raw
  payloads land on `_current` (one copy per source-entity tuple,
  refreshed every heartbeat) instead of being duplicated on every
  cycle. The write-amplification objection to filling `raw_data`
  disappears.
- **Enables truthful "device withdrawn from source" surfaces.** Today
  a device that disappears from S1 leaves stale observation rows
  behind. `_current.active = false` + `withdrawn_at` makes withdrawal
  first-class.

## Consequences

**Becomes easier:**

- Current-state queries — PK lookup, no `DISTINCT ON`.
- Cross-source disagreement queries (Raw tab common-field matrix,
  identity conflict detection) — direct join on identity tuple across
  `_current` rows keyed by different `source_binding_id`.
- Adding new sources / new entity types — writer primitive is the
  single point of observation-write contact.
- Historical audit — `_history` is a proper SCD-2 stream with real effective
  intervals and material payload projections sufficient to reconstruct
  historical readers without retaining full raw payloads.
- Source-withdrawal surfaces — first-class rather than inferred from
  missing rows.

**Becomes harder / required:**

- Every reader that references `entity_observations` must be repointed
  at `_current` or `_history`. Frozen reader inventory in root plan.
- Material-fields policy is a live artifact — wrong choices cause
  either write amplification or missed change events. Central config
  with algorithm version.
- Migration must handle post-hoc mutations mid-cycle (resolver +
  merge paths). Primitive must be re-entrant + preserve resolved IDs.
- `identity_candidates.observation_id` foreign key to old table
  (migration 0019) must migrate or retire before old-table rename can
  drop. If retired, findings preserve a stable current/history tuple or
  snapshot-run evidence reference so operator audit trails do not lose their
  triggering observation.
- `queue_registry` table row references the literal old-table name
  (migration 0014); must update in the same track.
- DESIGN.md line 16 + `docs/architecture.md` updated in the same
  track. `docs/architecture.md` gains a section describing the two-
  table observation model and the identity contract.
- Cross-service coordination: schema lives in operations, writers
  live in ingest. Both must deploy together (or dual-write phase
  as gated in the plan).
- Source bindings and collector references are retention-safe: observation
  evidence uses `PROTECT` or an explicit detach/archive path. Deleting source
  configuration cannot cascade-delete current or historical observations.
- Raw-data governance is explicit: current-only raw access is role-granted,
  redaction and logging boundaries are documented, tenant offboarding/deletion
  is defined, and history excludes raw payloads by default.
- Materialized-view consumers have an explicit tenant boundary because table
  RLS does not protect direct materialized-view reads; security-barrier
  wrappers or restricted grants are required where appropriate.

**Prohibited / rejected:**

- Retention job on `_current` as a substitute for the design.
  Retention on `_history` (closed versions only, indexed on
  `effective_to`) is a natural knob.
- Per-connector variation of material-hash algorithm. Per-entity-type
  policy in shared config is the intended flexibility.
- Overwriting resolved `device_id` / `client_id` on `_current` with
  NULL from a fresh connector write.
- Deleting the one open `_history` version under any retention rule.

## Supersedes or superseded by

- Refines ADR-0001 (source-agnostic observation pipeline) at the
  storage layer. Does not change the connector contract.
- Refines ADR-0003 (four-layer domain-storage split) — observation
  layer now has two physical tables mapping to its two jobs.
- Supersedes DESIGN.md line 16 "No parallel observation tables."
  DESIGN.md updated in the same track.
