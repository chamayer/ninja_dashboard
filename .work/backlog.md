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

## `device_session_current` counts CMDB syncs as device contact

- Reason deferred: real but currently unread. The matview aggregates
  `MAX(last_contact_at)` / `MAX(last_observed_at)` from
  `device_agent_presence_current` with no `entity_type` filter, so a CMDB
  sync counts as contact with the machine. Measured 2026-07-30: **856
  devices** have `last_contact_at` inflated by Hudu, plus 9 known only to
  Hudu.
- Why it is not urgent: the only application consumer
  (`views.py:2304`) reads `online_sources`, which is unaffected — Hudu sets
  no `is_online`, so it is filtered out of the online aggregation. Metabase
  may read the affected columns; not audited.
- Same defect class as the four fixed on 2026-07-30 (resolution, promotion,
  lifecycle, duplicate-records): an exclusion guard where the platform now
  has `operations.entity_types.is_identity_signal`.
- Fix: recreate `operations.device_session_current` with the contact
  aggregation joined to `operations.entity_types` and filtered to
  `is_identity_signal`. `device_agent_presence_current` itself stays
  unfiltered on purpose — it answers "which sources hold records on which
  devices", which `source_health_current.device_count` needs.
- Constraints: matview recreate, so it needs a migration and a refresh;
  check `refresh_device_session_current()` still matches after the rewrite.
- Trigger: anything starting to read `last_contact_at` from this matview, a
  Metabase question depending on it, or the next matview migration in this
  area.

## Root backlog rules

- Do not duplicate Operations-only items here.
- Do not retain completed milestone checklists.
- Move an item into `.work/plan.md` only when approved as active cross-service
  work.
