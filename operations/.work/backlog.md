# Operations deferred work backlog

This is the proposed successor to the genuinely open portion of
`operations/TODO.md`. Completed tracks and chronological history are excluded.

## UI roadmap

### Dashboard and fleet search

- Candidate scope: richer fleet dashboard cards and a fleet-wide device search
  in the header space.
- Dependency: select one bounded slice and define acceptance/validation in the
  active plan.
- Follow-up: remove the now-vestigial `client_switch` view and route when the
  replacement navigation is ready.

### Navigation and workflow consolidation

- Candidate scope: primary/admin navigation, client detail, Issues, Review,
  Config, System, and device-detail restructuring.
- Constraint: deliver in bounded waves; preserve bookmarks and permissions or
  document redirects/breakage.

### Bulk operator actions

- Candidate scope: finding resolution/snooze, suppress-from-row, patching-scope
  overrides, and exemptions.
- Constraints: audit, tenant scope, validation, and clear distinction between
  suppressing a finding and changing policy.
- Status: **Landed 0.57.0 / 0.58.0 / 0.59.0** — Wave UI-2.F.

### Business data capture (Wave UI-2.G) — deferred

- Candidate scope: add business fields to `Client` (tier via new
  admin-editable `ClientTier` table, MRR, account manager,
  renewal date, onboarding stage) to unblock Dashboard maturity
  (Wave UI-2.H: trend arrows, tier badges, revenue-weighted
  sort).
- Constraint: 5 nullable columns + 1 small seeded table — no
  backfill needed. Follows the "mappings live in data" rule
  (tier list admin-editable, not hardcoded).
- Blocks: Wave UI-2.H (Dashboard maturity). Both stay deferred
  together until picked up.

### Dashboard maturity (Wave UI-2.H) — blocked on G

- Candidate scope: trend arrows on portfolio grid, tier badges,
  revenue-weighted sort, renewal-risk heat, at-risk callouts
  (high MRR + degrading health).
- Blocker: Wave UI-2.G business data capture.

## Platform cleanup

### Retire legacy parity and agent-compliance paths

- Relevant areas: legacy parity report, agent-compliance code/schema,
  scheduler/manual endpoints, and Metabase consumers.
- Risk: destructive schema/code deletion.
- Trigger: consumer audit, verified native parity, backup, and explicit
  approval.

### Rename presence materialized view

- Status: **Landed 0.61.0** — renamed to `device_agent_presence_current`
  in migration 0047. Follow-up (below) covers the Metabase side.

### Device identity + layered entities (Track)

- Candidate scope: implement the model in decision record
  `operations/docs/decisions/0005-device-identity-and-layered-entities.md`.
- Introduces `Asset`, `OSInstance`, and `AgentInstance` as canonical layer
  entities with effective_from / effective_to windows. `Device` becomes a
  thin, learned identity anchor. Findings gain `source_layer` +
  `source_layer_entity_id` back-references. `v_device_current` flattening
  view supplies operator surfaces.
- Absorbs the previous "form-factor fallback correction" backlog item —
  under this model, agent presence cannot infer asset form factor by
  construction. "Unknown" becomes a legitimate value at every layer.
- Absorbs the identity-conflict rule: hostname-only observations do not
  merge; contested corroboration surfaces an identity-conflict finding.
- Track-sized. Migration path splits current `Device` columns into layer
  entity tables with backfilled effective windows; evaluators re-point to
  layer entities; composite evaluators declare layer dependencies.
- Constraint: preserve tenant/RLS behavior across four canonical tables;
  keep operator context (labels, notes, exemptions) on Device.
- Trigger: explicit approval to open the track. Cheaper before any further
  UI or evaluator work accrues on the flat Device model.

## Policy and workflow enhancements

- Coverage-requirement add/remove override semantics
- Per-device exemption UI
- Suppress-this-finding action
- Remaining hostname-to-device link sweep
- More actionable device-unenrolled presentation
- Profile suggestions for global-fallback clients
- ScreenConnect session pagination/cap verification

Each item needs a focused active plan before implementation.

## Consolidate side tables into the standard Findings surface

Principle: operator-visible findings live in `operations.findings` with a
`FindingType` row. Per-type side tables fragment the operator UX and
duplicate lifecycle plumbing. See
`memory/feedback_findings_single_surface.md` (2026-07-20).

### Retire `identity_candidates`

- Reason deferred: the table has live UI consumers today
  (`apps/core/views.py`, `templates/home.html`, `_admin_tabs.html`,
  `config/urls.py`, `context_processors.py`). Retirement requires
  migrating the admin surface to the standard findings queue filtered
  on `finding_type='identity_conflict'`, then dropping the table + URL
  + view.
- Status: `identity_conflict` FindingType emission landed in slice 3 of
  ADR-0005. Dual-write continues during the transition.
- Trigger: explicit approval for the destructive retirement.

### Audit other finding-like side tables

- Candidate scope: `merge_candidates` and any other tables that
  materialize operator-review workflows outside `operations.findings`.
- Trigger: consumer audit + per-table retirement plan.

## Activate layer-entity field-history audit trails

- Candidate scope: wire the significant-field audit tables (already
  scaffolded in ADR-0005 slice 1 — `asset_field_history`,
  `os_instance_field_history`, `agent_instance_field_history`) to
  fire when the resolver's attribute-sync detects a change on a
  significant field. Tables currently exist and are empty.
- Significant fields (per ADR-0005): `form_factor`, `serial`,
  `vm_uuid` on Asset; `os_name`, `os_version` on OSInstance;
  `agent_version` on AgentInstance. Heartbeat / last_seen churn is
  excluded.
- Design: BEFORE UPDATE trigger on each layer table, or explicit
  INSERT-audit at the resolver's UPDATE site. Trigger is bulletproof;
  explicit-write ties audit to the resolver's transactional scope
  and skips heartbeat noise more easily.
- Payoff: trends (e.g. "how often does the OS version change on
  Windows devices?") and forensics ("what agent_version was on
  device X on date D?") become native queries against the audit
  timeline.
- Trigger: explicit approval to open the track.
- **Not to be confused with** the abandoned "install-lifetime
  detection" idea — per ADR-0006, layer entities are attribute
  buckets, not lifecycle-window entities. Field history is the
  history mechanism.

## Metabase deprecation

### Metabase card parity audit (informs Operations build-out)

- Purpose: Metabase is planned for deprecation. Before turning it off,
  inventory every card in active use to learn what analytical surfaces
  operators actually rely on, so equivalent views can be built natively
  in Operations.
- Candidate scope:
  - Full read-only export of Metabase questions + dashboards from the
    `ninja-metabase` backing Postgres (question IDs, names, collection
    paths, dashboard placement, SQL, last-viewed / last-run signals if
    available).
  - Classify each card: (a) already covered by an Operations view,
    (b) needs an Operations equivalent, (c) obsolete / retire.
  - Produce a parity gap list feeding future Operations UI slices.
- Out of scope: fixing individual broken Metabase questions caused by
  Operations schema changes (renamed presence matview, retired
  `exemptions` column, etc.). These will be resolved by the Operations
  equivalent, not by patching Metabase SQL.
- Access: Metabase's Postgres uses env `MB_DB_*` on the `ninja-metabase`
  container (host `postgres`, port 5432, type postgres). Credentials in
  the compose env-file or mounted secret.
- Constraint: read-only. No writes to the Metabase backing store.
- Trigger: approved decision to begin Metabase sunset planning.

## Backlog rules

- Do not copy completed Tracks C, E, O, or other shipped milestones here.
- Do not store session transcripts or full production query results.
- Move only one approved slice at a time into `operations/.work/plan.md`.
