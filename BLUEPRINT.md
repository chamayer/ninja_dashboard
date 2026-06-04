# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Fix the Device Drilldown timeline parameter so changing the days
filter does not break the chart.

## Why

The `Install Results Over Time` card loads initially, but changing the
timeline window causes the query to fail in Metabase.

## Scope

**In:**
- Fix the Device Drilldown timeline query parameter casting.
- Keep the dashboard wiring and defaults unchanged.
- Compile-check the bootstrap after the edit.

**Out / separate investigation:**
- Any other dashboard parameter cleanup.
- Adding new Device Drilldown filters.
- Offline-device cleanup.

## Files to change

- `ingest/metabase_bootstrap.py`
  - Cast the Device Drilldown `days` parameter explicitly in the
    timeline query.
- `BLUEPRINT.md`
  - Track this task while it is in progress.

## Steps

1. Update the Device Drilldown timeline SQL to cast `days` safely.
2. Compile-check `ingest/metabase_bootstrap.py`.
3. Commit and push after approval.

## Open questions

- None.

## Status

in progress
