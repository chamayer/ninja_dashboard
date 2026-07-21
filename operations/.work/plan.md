# Active Operations work plan

Track: **Source-health derived state performance**

## Status

- Implementation complete — awaiting commit/deployment approval and deployed
  validation.

## Goal

Replace repeated raw observation/run-health aggregation in the Dashboard and
Sources page with a single tenant-scoped `source_health_current` materialized
view, refreshed through the existing derived-state coordinator.

## Scope

- In: source latest-observation, latest run/success, and agent-presence reach
  summaries; Dashboard and Sources page reads; refresh coordinator; migration
  and focused validation.
- Out: changing ingest semantics, queue state, source configuration, or UI
  layout; release/version changes.

## Affected files

- `apps/core/migrations/0061_source_health_current.py` — materialized view,
  grants, refresh function, and coordinator update.
- `apps/core/views.py` — consume the derived read surface on Dashboard and
  Sources.
- `operations/.work/plan.md` — active checkpoint.

## Decisions

- Use one broader source-health derived surface, not a Dashboard-specific
  cache. It serves both existing consumers and keeps raw observations
  auditable.
- Retain live source-run-queue and recent-history reads on Sources: they are
  workflow/history data, not current source-health state.
- Refresh source health after device-agent presence because reach derives from
  that materialized view.

## Validation

- `python manage.py check`
- `ruff check apps/core/views.py`
- `ruff format --check apps/core/views.py apps/core/migrations/0061_source_health_current.py`
- migration SQL review and `git diff --check`
- after approved deployment: Dashboard query timing and Sources page smoke.

## Current checkpoint

- Live Dashboard render improved from 5.54 s to 1.56–1.83 s after removing
  the global software-decision count.
- Query timing attributes ~1.25 s of the remaining render to
  `MAX(observed_at) GROUP BY platform` over `entity_observations`.
- Added migration 0061 and rewired Dashboard/Sources reads to the shared
  source-health materialized view. The view SQL was parsed with live Postgres
  `EXPLAIN`; local Python compilation, Django checks, migration formatting,
  and `git diff --check` pass.
- `ruff check apps/core/views.py` has pre-existing whole-file violations, so
  it is not a useful focused gate without unrelated cleanup.

## Next action

- Commit the Operations migration, views, and plan only; deploy and measure
  Dashboard and Sources against the refreshed derived state.
