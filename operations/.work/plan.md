# Active Operations work plan

Track: **Patching status and Ninja activity evidence**

## Status

- Implemented locally; awaiting deployed-stack smoke check before release.

## Goal

Make Patching a status overview of the managed estate, with clear denominators
and drill-throughs, and make Ninja-collected patch activity inspectable at both
fleet and device level.

## Scope

- `apps/core/views.py`, `apps/core/device_status.py`,
  `apps/core/client_workspace.py`, and the Patching, Device, and Dashboard
  templates.
- No schema, ingestion, retention, or finding-contract changes.

## Decisions

- **Active device** means a non-retired device has contacted a source within
  seven days. It is shared across Dashboard, Clients, Devices, and Patching,
  and is distinct from `online now` (the 24-hour availability signal).
- **In patching scope** is a policy decision, not activity.
- **Recent patch activity** means a Ninja patch scan/state observation or
  install outcome within the existing 35-day stalled-patching window.
- Status cards use explicit denominators and drill into the devices behind the
  measure. Exception findings remain supporting detail, not the page framing.
- Ninja patch facts are evidence. Show their event time, collection time,
  patch state/outcome, and the collected payload where present; never imply a
  payload field was normalized when it was merely collected raw.

## Steps

- [x] Add scoped patch-status population and client posture queries.
- [x] Reframe `/patching/` around status cards and client posture; preserve
  the existing work list below the overview.
- [x] Add fleet activity evidence and device-level Ninja patch timeline.
- [x] Centralize the active-device definition and correct Dashboard/Client
  labels that previously used "active" for all managed devices.
- [x] Run focused tests/checks and document actual validation.

## Validation plan

- Django system check, template loading, targeted patching tests where present,
  Ruff/format checks for changed Python, and `git diff --check`.

## Validation

- `python -m compileall apps/core/views.py` — pass.
- `python manage.py check` — pass.
- Template loading for Patching, Activity, and device detail — pass.
- `pytest apps/core/tests -q` — 23 passed.
- `ruff check apps/core/views.py --select F,E9` and `git diff --check` — pass.
- Local Django settings have no database engine, so the new SQL has not been
  run against the deployed Postgres schema from this workstation.

## Checkpoint

- `/patching/` now distinguishes total, active (7-day contact), active in
  scope, recent Ninja patch activity (patch state or install evidence in 35
  days), quiet, never patched, and reboot pending. Every status card drills to
  devices; client posture uses the same definitions. The device Activity tab
  now includes Ninja messages and raw payloads plus retained patch facts; the
  fleet Activity page combines both evidence sources when no outcome-status
  filter is selected. Home now shows active out of managed, Devices has a
  matching Active drilldown, and Client Overview uses active out of total as
  its primary estate measure.

## Next action

- Run final local validation, then commit and push this scoped change without
  staging the existing `org_index.html` worktree change. A deployed-stack
  smoke check remains the next operational step.
