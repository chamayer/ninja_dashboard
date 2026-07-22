# Active Operations work plan

Track: **Operator-first device Identity tab**

## Status

- In progress. The deployed tab is technically correct but presents raw
  diagnostics before operator-relevant identity evidence.

## Goal

Make device Identity a calm review surface: summarize source coverage and
meaningful normalized-field conflicts first, while retaining the complete
canonical matrix and raw source payloads as advanced forensic detail.

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

- A cross-source value difference is review evidence, not automatically an
  error; the UI must state that plainly.
- Keep full normalized values and source-native payloads available under
  Advanced details rather than removing diagnostic capability.
- Only fields with conflicting normalized values appear in the default review
  section; source identifiers remain directly visible.

## Steps

- [x] Inspect existing Identity-tab markers and layout.
- [x] Add concise summary/conflict presentation data.
- [x] Restructure the template around review-first and advanced details.
- [ ] Commit, deploy, and validate the affected Identity tab and issue link.

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
