# Root and cross-service deferred work

This is the proposed successor to the root-level open-work portion of
`TODO.md`. Operations-only items belong in `operations/.work/backlog.md`.

## Dashboard reporting performance

- Reason deferred: broad historical and compliance cards previously exceeded
  acceptable response times.
- Relevant areas: reporting materialized views, Metabase bootstrap SQL, and
  activity/patch aggregations.
- Trigger: a removed or deferred card is prioritized for restoration.
- First verification: time candidate SQL against representative live data
  before changing dashboard definitions.

## Ingest domain separation

- Reason deferred: scheduling and startup orchestration remain shared even
  though domain packages exist.
- Relevant paths: `ingest/main.py`, domain entrypoints, shared scheduler and
  bootstrap plumbing.
- Constraint: do not break current schedules, manual-run endpoints, migrations,
  or shared-client reuse.
- Trigger: an approved runtime isolation or independent deployment requirement.

## Legacy agent-compliance cutover

- Reason deferred: native Operations paths are substantially implemented, but
  legacy consumers and destructive retirement require audit.
- Relevant areas: `ingest/agent_compliance/`, scheduler/manual endpoints,
  legacy schema, Metabase consumers, configuration, and migration history.
- Constraints: backup, consumer audit, verified parity, and explicit
  destructive approval.
- Trigger: P7 cutover approval.

## Legacy Ninja snapshot archival, deletion, and disk reclamation

- Reason deferred: the generic ingest cutover must first prove that current,
  change-history, compatibility, and daily-rollup consumers are correct. Disk
  reclamation is operational cleanup, not part of the generic deployment.
- Relevant objects: `ninja_core.device_snapshots`,
  `ninja_core.device_health_snapshots`, their indexes and compatibility views,
  and the storage volume that contains them.
- Preconditions: both Ninja endpoint namespaces are authoritative through the
  generic contract; every named current/session/health/troubleshooting/trend
  consumer is verified; retention/archive policy is approved from aggregate
  30/90/365-day sizing; backup and restore rehearsal pass.
- Constraints: do not touch Agent Compliance; do not bundle historical
  deletion, archive, table truncation, partition removal, vacuum/repack, or
  filesystem reclamation into the generic deployment.
- Trigger: explicit post-cutover operational approval with an exact retained,
  archived, and deleted row/time range plus rollback and disk-reclamation plan.

## Honour `source_bindings.schedule` (replaces cadence-by-capability)

- Reason deferred: `operations.source_bindings.schedule` exists and is
  populated (empty string today) but **nothing reads it** — every source is
  collected on one shared cycle. Adding Hudu made this bite: it is ~122
  paginated requests, changes daily at most, and `load_sources()` orders by
  `s.name`, so `Hudu` precedes every agent source and would delay them on
  each 4-hour cycle.
- **Interim measure now in place (must be reverted by this work):**
  collection cadence is partitioned by source *capability* rather than by the
  per-binding schedule —
  `ingest/source_observations.py::is_identity_source`,
  `ingest/main.py::run_agent_observations_once` (filtered to identity
  sources), `ingest/main.py::run_documentation_observations_once`, the
  `documentation_observations_cycle` scheduler job, and
  `DOCUMENTATION_SCHEDULE_HOURS` in `ingest/config.py`.
- Revert path: delete the documentation job and both source filters. Or,
  without a code change, set `DOCUMENTATION_SCHEDULE_HOURS` equal to
  `AGENT_COMPLIANCE_SCHEDULE_HOURS` to restore a single effective cadence.
- Why it is only interim: capability is a poor proxy for cadence. Two
  documentation sources may warrant different intervals, and a per-source
  schedule is already modelled in the database — this hardcodes in Python
  what the schema was designed to express.
- Constraints: must not change existing agent-source cadence without
  approval; per-binding schedules need a defined format (cron vs interval)
  and a sane default for the four existing bindings.
- Trigger: a third collection cadence being needed, or any source requiring
  a schedule that differs from others of its capability.

## `device_session_current` counts CMDB syncs in `last_observed_at`

- Corrected measurement 2026-07-30: **31 devices**, of which 9 would become
  null (known only to Hudu). An earlier note in this file said 856 — that was
  measured with `COALESCE(last_contact_at, last_observed_at)`, which is the
  *lifecycle* formula (already fixed in `_sync_lifecycle_status`), not what
  this matview uses.
- `last_contact_at` is **not** affected: CMDB rows set no `last_seen_at`, so
  it is null for them and `max()` already ignores it. Verified: 0 devices
  change.
- No application code reads `last_observed_at` from this matview. The only
  consumer (`views.py:2304`) reads `online_sources`, which is unaffected —
  CMDB rows never set `reported_online`.
- Deliberately not fixed: recreating a matview with 3 indexes and 4 grants in
  production to correct 31 rows of an unread column is not worth the
  deployment risk. A migration was written, validated, and discarded on that
  basis.
- Fix when touched: add `LEFT JOIN operations.entity_types` and filter the two
  contact aggregates on `is_identity_signal`. Leave
  `device_agent_presence_current` unfiltered — it answers "which sources hold
  records on which devices", which `source_health_current.device_count` needs.
- Trigger: any consumer starting to read `last_observed_at` from this matview,
  a Metabase question depending on it, or the next migration in this area.

## Preserve Operations availability during derived refresh

- Evidence: the `0.101.4` full-cycle validation on 2026-08-03 ran Inventory
  current-fact refresh for about 8 minutes 42 seconds with multiple concurrent
  PostgreSQL workers. During that interval, the authenticated Software surface
  returned one HTTP 500 and two Gunicorn workers timed out. The refresh and
  cycle later completed, both services remained healthy, and the following
  three-minute window had zero further 500s or worker timeouts.
- Required outcome: normal full collection/derived refresh must not block
  Operations readers through the 60-second Gunicorn timeout. Reconcile the
  actual Inventory refresh path with the design requirement for dependency-
  ordered concurrent materialized-view refreshes; also prevent redundant
  refresh workers from running the same expensive chain concurrently.
- Constraints: preserve transactionally coherent current facts, RLS/grants,
  existing reader schemas, and failure visibility. Do not hide the issue by
  merely increasing the web timeout.
- Validation gate: a representative full cycle under normal queue activity
  completes with zero Operations HTTP 500s and worker timeouts while the
  Software surface remains responsive.
- Trigger: approve this cross-service availability/performance design before
  generic Ninja reader cutover.

## Root backlog rules

- Do not duplicate Operations-only items here.
- Do not retain completed milestone checklists.
- Move an item into `.work/plan.md` only when approved as active cross-service
  work.
