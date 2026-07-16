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
