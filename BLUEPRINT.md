# Goal

Bring the live v0.35 dashboard set under the agreed fast-load standard
by fixing the remaining slow broad card queries.

# Why

After v0.35.1 went live, dashboard shell/API loads passed. v0.35.2
fixed `Patch Installs per Day`, but retiming still found slow broad
cards and two Client Patch Review breakdowns had been removed from the
active layout:

- `Patching Devices per Day`: about 3.2s.
- `Warnings by Category (30d)`: about 2.7s.
- `System Reboots per Day`: about 1.7s.
- `Fully patched % by Operating System`: restore and optimize.
- `Fully patched % by Device Type`: restore and optimize.

# Scope

- Keep the seven-dashboard information architecture unchanged.
- Optimize the measured slow cards without hiding them.
- Preserve click-through behavior.
- Prefer existing rollups/indexes where possible.
- Add reporting materialized views where raw event scans are still slow.
- Do not redesign dashboard names, nav, or card placement in this pass.

# Files to change

- `ingest/metabase_bootstrap.py`
  - Update slow card SQL and/or remove non-actionable slow cards from
    first-load layouts.
- `sql/migrations/068_patch_dashboard_activity_rollups.sql`
  - Add recent patch-warning and reboot activity reporting views.
- `ingest/activities/ingest.py`
  - Refresh the new activity reporting views.
- `CHANGELOG.md`
  - Record v0.35.3 performance pass.
- `SESSIONS.md`
  - Record measurements, decisions, validation.
- `TODO.md`
  - Move any deferred rollup/materialized-view work.
- `VERSION`
  - Bump to 0.35.3.

# Steps

1. Test candidate SQL/index approach for the remaining slow cards against the
   live DB.
2. Restore the hidden Client Patch Review cards and optimize the SQL paths.
3. Compile locally.
4. Commit/push after validation.
5. Let deploy/bootstrap apply.
6. Retime live dashboard API and card sweep.

# Open questions

- None.

# Status

v0.35.3 implemented locally; compile and generated-card checks pass.
Commit, deploy/bootstrap, and live retiming remain.
