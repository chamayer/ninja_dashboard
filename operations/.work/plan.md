# Active Operations work plan

Track: **Normalize Identity-tab observation JSON**

## Status

- In progress. The deployed Identity tab raises an exception when a JSON object
  is returned by the database driver as JSON text.

## Goal

Make Identity-tab raw snapshot formatting tolerate JSON object values returned
as strings while preserving the current object-shaped display behavior.

## Scope

- **In:** defensive JSON-object normalization in the raw snapshot formatter,
  regression coverage, focused validation, commit, and deployment.
- **Out:** observation-schema changes, rewriting stored data, or changing the
  raw-tab field model.

## Affected files

- `apps/core/views.py`
- `apps/core/tests/test_dashboard.py`
- `.work/plan.md`
- `.work/backlog.md`

## Decisions

- Treat a decoded JSON object as canonical only when its Python value is a
  mapping. Parse JSON text that decodes to an object; safely treat invalid or
  non-object values as empty objects for this display-only surface.

## Steps

- [x] Trace the deployed Identity-tab exception.
- [x] Confirm stored canonical data is valid JSON objects.
- [x] Normalize JSON-object display inputs and add regression coverage.
- [ ] Commit, deploy, and exercise the affected page.

## Validation plan

- Run the focused regression test, Django checks, Ruff checks/formatting for
  changed files, and a deployed request smoke test for the affected tab.

## Checkpoint

- Production traceback: `_build_raw_snapshot_view` calls `.keys()` on a string
  at `apps/core/views.py:1511`.
- The three active observations for the affected device store
  `canonical_data` as JSON objects, so this is driver/display normalization,
  not corrupt observation data.
- Local validation passed: `pytest apps/core/tests/test_dashboard.py` (15
  tests), focused Ruff check/format check for the test file, `python manage.py
  check`, and `git diff --check`. `apps/core/views.py` retains unrelated
  repository-wide Ruff findings; the new helper introduces none.

## Next action

- Commit, push, deploy, and verify the affected Identity tab returns success.
