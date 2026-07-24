# Active Operations work plan

Track: **Patching page perf — matview-backed posture rollup**

## Status

- Implemented locally; awaiting deployed-stack confirmation.

## Goal

Cut `/patching/` page latency by eliminating request-time aggregation of the
467k-row `ninja_patches.patch_facts` table and by consolidating the fleet and
per-client posture rollups into a single query.

## Scope

- `sql/migrations/070_device_patch_activity.sql` — new per-device matview.
- `ingest/patches/ingest.py` — refresh the new matview alongside the existing
  patch summary matviews.
- `apps/core/views.py::patching_queue` — read the matview instead of
  aggregating `patch_facts`; collapse the two GROUP BY queries into one
  `GROUPING SETS` execution and roll up in Python.

## Decisions

- Per-device `last_patch_activity_at` lives in a **new standalone matview**
  (`ninja_patches.device_patch_activity`) rather than being folded into
  `device_patch_signal`. `device_patch_signal` has a dependent matview
  (`device_troubleshooting_signal`) that would have to be dropped and
  recreated in lockstep; keeping activity standalone contains the change.
- No dual-write of patches to `entity_observations`. The per-KB volume
  (~83k `patch_state` + ~384k `install_outcome`) would flood a surface we
  have been deliberately keeping bounded, and the per-device posture the
  page actually reads is only ~5k rows.
- No operations-owned per-device patch snapshot introduced. Source
  decoupling of patches (matching what software went through) is real debt
  but not justified by any current second-source requirement; revisit only
  when a second patch source appears.
- Findings surface stays authoritative for the finding-type tiles; the
  posture status cards keep their own definitions because `has_recent_patch_activity`
  is not currently a finding.

## Steps

- [x] Add `ninja_patches.device_patch_activity` matview + indexes.
- [x] Refresh it in `_refresh_summary_views` after each patch ingest cycle.
- [x] Rewrite `patching_queue` posture CTE to read the matview.
- [x] Consolidate fleet + per-client rollups into one `GROUPING SETS` query.
- [x] Validate compile, Django check, template loading, tests, and dry-run
  the query against the deployed database.

## Validation plan

- `python -m compileall apps/core/views.py`.
- `python manage.py check`.
- Template loading for the four affected templates.
- `pytest apps/core/tests -q`.
- Dry-run the migration and rewritten query in a transaction against the
  deployed database via the workspace helper, then `ROLLBACK`.

## Validation

- `python -m compileall apps/core/views.py` — pass.
- `python manage.py check` — pass.
- Template loading (`patching_queue.html`, `patch_activity.html`,
  `device_detail.html`, `org_index.html`) — pass.
- `pytest apps/core/tests -q` — 23 passed.
- Deployed-DB dry-run (transaction + `ROLLBACK`): matview build 652 ms
  (one-time); rewritten posture query 123 ms end-to-end, returning
  correct totals (5183 devices, 4334 active, 2231 active-in-scope, 2152
  recent, 8 quiet, 103 never patched, 69 reboot pending) plus 75
  per-client rows in one round trip.

## Checkpoint

- The old view executed the posture CTE **twice** per request and each
  execution aggregated `MAX(...)` over 467k `patch_facts` rows. The rewrite
  reads the new 3k-row `device_patch_activity` matview instead, and runs
  the fleet + per-client rollups in a single `GROUPING SETS` query.

## Next action

- Commit as a scoped release (VERSION 0.82.1), push to `origin` first
  (Portainer redeploys), then to the `a-m-rose` mirror.
