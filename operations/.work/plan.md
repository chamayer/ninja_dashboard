# Active Operations work plan

Track: **Client workspace dashboard language**

## Status

- Complete. The client workspace now uses dashboard-oriented language, keeps
  requirement-profile names in configuration, and exposes direct configuration
  links.

## Goal

Make the client directory and overview answer how a client is doing, while
leaving findings and configuration workflows behind clear existing links.

## Scope

- **In:** `templates/org_index.html` and presentation labels in
  `apps/core/client_workspace.py`.
- **Out:** changing findings, policy data, workflow routing, or dashboard
  calculations.

## Affected files

- `templates/org_index.html`
- `apps/core/client_workspace.py`
- `.work/plan.md`

## Decisions

- Requirement-profile names are configuration metadata. They remain available
  under Client administration but are not displayed as the directory/client
  subtitle.
- Status vocabulary should describe a dashboard state, not instruct an
  operator to process a queue. Existing state keys, queries, filters, and
  links remain unchanged.
- Configuration stays out of the read-only dashboard. Both the scoped overview
  and directory expose a direct, unambiguous route to its existing Admin page.

## Steps

- [x] Remove the exposed profile-name subtitles.
- [x] Retitle client overview, status, table, and directory labels.
- [x] Add explicit configuration links.
- [x] Run Django/template validation and inspect the rendered-text diff.

## Validation plan

- `python manage.py check`, targeted client-workspace tests, and `git diff --check`.

## Checkpoint

- Confirmed “Not clockable” comes from the assigned requirement-profile name,
  rendered directly beneath the client name in both client and directory views.
- Current labels use queue language including “Needs attention”, “What needs
  review”, “Next step”, and “Admin review”.
- Replaced those labels with neutral dashboard terms such as “Open items”,
  “Item”, “Details”, “Configuration”, “Attention”, and “Watch”. The underlying
  status keys, filtering, destinations, and data remain unchanged.
- Validation: `python manage.py check` and
  `pytest -q apps/core/tests/test_client_workspace.py` (8 passed); `git diff
  --check` passed.

## Next action

- None. A separate uncommitted change exists in `../ingest/core/devices.py`
  and was intentionally left untouched.
