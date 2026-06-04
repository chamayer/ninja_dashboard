# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Rename the patch KPI cards so the dashboards distinguish device
compliance from patch progress, and add those headline trend views to
the Trends dashboard.

## Why

The current `Patch Compliance` label is ambiguous for an MSP operator.
The landing page should answer "are devices fully patched right now?"
with one at-a-glance score, while the status dashboards should show the
broader patch progress context alongside it.

## Scope

**In:**
- Rename the command-center headline KPI to `Devices Compliant %`.
- Split Overall Status and Org Overview into `Devices Compliant %` and
  `Patch Progress %` cards.
- Add trend cards for the same two metrics.
- Update release docs and versioning.

**Out / separate investigation:**
- Reworking the underlying patch-compliance formula.
- Adding new data sources or schema changes.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Rename the existing compliance cards and add trend KPIs.
- `CONTEXT.md`
    - Update the dashboard / metric terminology if needed.
- `VERSION`
    - Bump for the dashboard update.
- `CHANGELOG.md`
    - Document the renamed KPI cards and trend additions.
- `SESSIONS.md`
    - Record the dashboard rework and rationale.
- `TODO.md`
    - Move any deferred follow-up into Backlog if one appears.

## Steps

1. Rename the relevant card titles and SQL aliases.
2. Add the trend cards for devices-compliant and patch-progress.
3. Compile-check the bootstrap.
4. Update docs and version.
5. Commit and push, then report the short hash.

## Open questions

- Whether the new status-dashboard cards should keep the old
  compliance formula or expose a new patch-progress denominator.

## Status

in progress
