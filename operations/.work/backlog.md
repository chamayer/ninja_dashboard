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

- Candidate: rename the historically narrow agent-presence name now that the
  structure represents broader entity presence.
- Constraint: whole-repository and consumer audit; no behavioral change.

### Form-factor fallback correction

- Concern: source-agent presence alone can cause unknown form factor to be
  labeled physical.
- Trigger: next identity-resolver correction or onboarding of source-only
  clients.

## Policy and workflow enhancements

- Coverage-requirement add/remove override semantics
- Per-device exemption UI
- Suppress-this-finding action
- Remaining hostname-to-device link sweep
- More actionable device-unenrolled presentation
- Profile suggestions for global-fallback clients
- ScreenConnect session pagination/cap verification

Each item needs a focused active plan before implementation.

## Backlog rules

- Do not copy completed Tracks C, E, O, or other shipped milestones here.
- Do not store session transcripts or full production query results.
- Move only one approved slice at a time into `operations/.work/plan.md`.
