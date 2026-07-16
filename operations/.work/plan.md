# Active Operations work plan

This checkpoint records concurrent Operations work observed during the
documentation-organization rollout. The organization work did not modify the
listed application files.

## Status

- Complete — the owning workflow released the dashboard refinement as version
  0.50.5, commit `122a303`.

## Goal

- Expand the "Needs immediate attention" dashboard list while keeping the
  panel compact and make the fleet overview label more explicit.

## Scope

- In:
  - Increase the severe multi-domain client query limit.
  - Make the attention list scrollable and show its item count.
  - Rename the Fleet overview label to Devices with client context.
- Out:
  - Finding evaluation semantics, schema, routes, or other dashboard areas.
  - Legacy schema deletion.
  - Unrelated ingest or identity changes.

## Files involved

- `operations/apps/core/views.py`
- `operations/templates/home.html`
- Root VERSION and CHANGELOG only if the owning workflow prepares a release.

## Steps

- [x] Reconcile BUILD_BLUEPRINT with current release history.
- [x] Confirm the fleet-overview BUILD_BLUEPRINT is completed and stale.
- [x] Record the two uncommitted application files without changing them.
- [x] Confirm fleet-wide header search was released in version 0.48.1.
- [x] Confirm the first operational-domain dashboard rework was released in
  version 0.48.2.
- [x] Confirm navigation consolidation and the client-portfolio dashboard
  research pass were released through version 0.50.1.
- [x] Confirm releases through 0.50.4 from VERSION and CHANGELOG.
- [x] The owning workflow released the 30-row limit and scroll behavior.
- [x] VERSION and CHANGELOG were updated by the owning workflow.
- [ ] Focused validation was not independently rerun during the documentation
  organization review.

## Decisions

- Context: Version 0.50.3 tightened the attention panel to five severe
  multi-domain clients. The current diff raises the query limit to 30 and
  contains the longer result in a scrollable list.
- Options considered:
  - Keep the five-row hard cap.
  - Return more qualifying clients and constrain display height.
- Candidate decision: Use the larger result set with a scrollable panel.
- Rationale: Preserves visibility of qualifying clients without allowing the
  exception panel to dominate the page.
- Consequences: Query cost and usability should be checked with realistic
  client counts.
- Promote durable reasoning to `operations/docs/decisions/`.

## Validation

- [ ] Focused Django view/template or request check.
- [ ] Confirm UI labels use US English and human-readable terms.
- [ ] Confirm the panel remains usable with more than five rows.
- [ ] `git diff --check`.

## Current checkpoint

- Stack version 0.50.5 is current.
- Patching UI and Wave A label/filter groundwork are released.
- Fleet-wide device/client search is released in the header.
- Primary navigation is consolidated and the dashboard is framed around
  client-portfolio triage.
- The removed client picker left a vestigial `client_switch` route for later
  cleanup.
- BUILD_BLUEPRINT's fleet-overview task is already completed.
- No tracked application diff remained when version 0.50.5 was observed.
- The documentation-organization rollout did not modify those application
  files.

## Remaining blockers

- Independent validation evidence was not available to the organization
  review.

## Next action

- Use this completed checkpoint until the next nontrivial Operations task
  replaces it. Revalidate the panel if its behavior changes.

## Completion

- Mark complete only after actual validation and already known root
  release/commit information is recorded.
- Do not create an extra commit solely to add that commit's own hash here.
- Keep this completed plan until the next nontrivial Operations task replaces
  it.
