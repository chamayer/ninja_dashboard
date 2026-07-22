# Active Operations work plan

Track: **Merged device Identity record**

## Status

- In progress. The Identity tab must present collected data as a neutral,
  grouped merged record rather than an issue/review surface.

## Goal

Make device Identity a neutral, grouped merged record: show combined values
with quiet source attribution, then retain all per-source fields in collapsed
reference panels.

## Scope

- **In:** Identity-tab presentation, conflict/coverage summary data, focused
  template tests and validation.
- **Out:** changing identity resolution, source observations, merge behavior,
  or raw-data retention.

## Affected files

- `apps/core/views.py`
- `templates/device_detail.html`
- `apps/core/tests/`
- `.work/plan.md`

## Decisions

- Source differences are alternative reports for the same field, never an
  alert state in this tab.
- Source attribution is muted parenthetical context beside each value.
- Each collapsed source panel lists every source-native field, not only fields
  absent from the merged record; raw JSON remains a final fallback.

## Steps

- [x] Inspect existing Identity-tab markers and layout.
- [x] Add concise summary/conflict presentation data.
- [x] Restructure the template around review-first and advanced details.
- [ ] Replace review framing with the merged-record presentation.
- [ ] Show all fields in collapsed per-source panels.
- [ ] Validate, deploy, and exercise the affected Identity tab and issue link.

## Validation plan

- Test the summary/conflict grouping independently.
- Run Django checks, focused tests, template rendering, formatting, and diff
  checks.
- Exercise the deployed affected Identity tab after approved deployment.

## Checkpoint

- The warning triangle is intentionally emitted for any normalized field with
  multiple reported values; “1 source” is informational coverage only.
- The current tab leads with the full field matrix and raw payloads, which
  makes it read as a debug surface.
- The device-header Issues link supplied `device`, but Findings queue filters
  by `subject_id`; the query parameter is now corrected.
- Local validation passed: Django checks, focused dashboard tests (15), and
  whitespace diff validation.
- Prior hotfixes are deployed: `7c0f334`, `ae46f38`, and `1b61016`.

## Next action

- Commit, deploy, and validate the redesigned Identity tab and issue link.
