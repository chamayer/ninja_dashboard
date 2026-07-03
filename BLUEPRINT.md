# Goal

Bring the live v0.35 dashboard set under the agreed fast-load standard
by fixing the remaining slow broad card queries.

# Why

After v0.35.1 went live, dashboard shell/API loads passed, but the
card sweep still found slow broad cards:

- `Patch Installs per Day`: about 3.5s.
- `Warnings by Category (30d)`: about 2.6s.
- `Fully patched % by Operating System`: about 2.1s.
- `Fully patched % by Device Type`: about 2.0s.
- `System Reboots per Day`: about 1.9s.

# Scope

- Keep the seven-dashboard information architecture unchanged.
- Optimize or demote only the measured slow cards.
- Preserve click-through behavior.
- Prefer existing rollups/indexes where possible.
- Add a migration only if query tests show the slow path needs it.
- Do not redesign dashboard names, nav, or card placement in this pass.

# Files to change

- `ingest/metabase_bootstrap.py`
  - Update slow card SQL and/or remove non-actionable slow cards from
    first-load layouts.
- `sql/migrations/067_patch_dashboard_perf_indexes.sql`
  - Add targeted indexes if direct SQL tests justify them.
- `CHANGELOG.md`
  - Record v0.35.2 performance pass.
- `SESSIONS.md`
  - Record measurements, decisions, validation.
- `TODO.md`
  - Move any deferred rollup/materialized-view work.
- `VERSION`
  - Bump to 0.35.2.

# Steps

1. Test candidate SQL/index approach for the five slow cards against the
   live DB.
2. Apply the smallest code/migration change that gets broad cards under
   target.
3. Compile locally.
4. Commit/push after validation.
5. Let deploy/bootstrap apply.
6. Retime live dashboard API and card sweep.

# Open questions

- None. If a card remains slow after indexes, demote it rather than
  delaying the whole dashboard on an analytical chart.

# Status

implemented locally; commit, deploy, bootstrap, and live retiming remain.
