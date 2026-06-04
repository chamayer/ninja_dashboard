# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Fix the dashboard org filter UX, add the missing Device Drilldown org
filter, and add compact count cards for the active-patching KPIs.

## Why

The operator keeps needing the same host, ingest, Metabase, Postgres,
and probe commands. A single reference file makes the workflow faster
and reduces drift from memory.

## Scope

**In:**
- Convert the broken Organization dropdowns on the affected dashboards
  into real text search boxes.
- Add an Organization filter to Device Drilldown.
- Add compact count cards for the active-patching KPI pages without
  bloating the layouts.

**Out / separate investigation:**
- Any offline-device cleanup.
- Offline-device cleanup.
- Reworking existing docs beyond the new reference file.

## Files to change

- `HANDY_COMMANDS.md`
  - Keep the new reference file in the repo.
- `ingest/metabase_bootstrap.py`
  - Update org filters, Device Drilldown, and compact KPI counts.
- `BLUEPRINT.md`
  - Track this task while it is in progress.
- `SESSIONS.md`
  - Record the dashboard update once it is done.

## Steps

1. Patch the bootstrap for org search, Device Drilldown org filter,
   and count cards.
2. Compile-check the bootstrap.
3. Update the session log.
4. Commit and push after approval.

## Open questions

- None.

## Status

in progress
