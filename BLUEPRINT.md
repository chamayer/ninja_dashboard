# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Make the second patch KPI explicit: it should mean fully patched among
patching devices, not fully patched across the whole active fleet.

## Why

The current `Fully patched devices %` wording reads like a percent of
all devices, but the intended denominator is the actively patching
subset. The formula and title need to agree so operators do not read
the card as fleet-wide compliance.

## Scope

**In:**
- Keep the Command Center count cards.
- Rename the Command Center headline KPI to `Actively patching %`.
- Recompute the second KPI as fully patched within the patching-device
  subset.
- Rename the second KPI to `Fully patched % (patching devices)`.
- Keep the existing filters intact on the affected dashboards.
- Update release docs and versioning.

**Out / separate investigation:**
- Reworking the underlying patch-state classifier.
- Adding new data sources or schema changes.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Adjust the second KPI formula and rename the visible card
      labels.
- `CONTEXT.md`
    - Update the operator-facing metric definitions.
- `VERSION`
    - Bump for the dashboard update.
- `CHANGELOG.md`
    - Document the KPI split and label changes.
- `SESSIONS.md`
    - Record the dashboard rework and rationale.
- `TODO.md`
    - Move any deferred follow-up into Backlog if one appears.

## Steps

1. Rename the relevant card titles and SQL aliases.
2. Keep the count cards on Command Center and preserve the active
   patching headline.
3. Update the fully-patched KPI formula and label everywhere it is
   shown.
4. Compile-check the bootstrap.
5. Update docs and version.
6. Commit and push, then report the short hash.

## Open questions

- None.

## Status

done — committed as 148de4e
