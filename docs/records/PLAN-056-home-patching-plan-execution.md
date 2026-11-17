# PLAN-056 Home Patching plan-only diagnostic

## Bounded protocol

User approved one execution on 2026-11-10.

- Target: `am-ch-01`, Operations container, existing application database role.
- Scope: read device-status policy once; call the Home Patching summary reader
  once under tenant 1 and a repeatable-read, read-only transaction. Intercept
  its one main SQL statement and send the exact statement and parameters to
  `EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without `ANALYZE`.
- The interception returns an in-process synthetic summary row only so the
  reader can finish; the business query itself is never executed. The reader's
  summary-relation `to_regclass` check remains a single read.
- Limits: 3-second statement timeout, 1-second lock timeout, 5-second idle
  transaction timeout, and 60-second process deadline. Stop on source-hash or
  query-shape mismatch, first error, missing plan, or timeout. No retry, HTTP,
  session, template, job, cache, cancellation, write, role change, or output of
  result values/query text. Emit only bounded plan-node metadata, elapsed plan
  time, SQLSTATE/error type, and closure status.
- Gates: runtime hashes for `patching_reads.py`, `computer_reads.py`, and
  `device_status.py`; AST gate requires one interpolated main query in
  `home_summary`. The collector passed local syntax parsing and the registry
  validator before execution.

## Approved invocation outcome — 2026-11-10

One run through `Invoke-DevTool.ps1` on `am-ch-01`; all runtime source gates
passed. Own backend PID 359561. The summary-relation check and main query plan
completed; non-ANALYZE planning took 0.079 s. The collector returned 52 nodes,
`truncated=false`, and `plan_finished status=0 connection_closed=true`.
`actual_execution=false`; the business aggregation was not run.

The root is an Aggregate with estimated cost 5,138.31 and one output row. The
main current-computer branch includes sequential scans of `devices` (6,260
estimated rows), `device_patching_scope_current` (6,391) and
`device_session_current` (19,857), joined with ownership rows (5,781). The
activity side scans `ninja_patches.device_patch_activity` (2,850 estimated
rows); the outcome-count lookup uses `patch_outcome_counts_pkey`. A separate
source-link branch estimates 13 Ninja links. These are planner estimates and
access paths, not actual counts, elapsed execution, or cost attribution. The
plan completed quickly but does not explain the earlier 3-second reader
deadline; actual reader execution and other Home components remain
uncharacterized here.

The collector matched SHA-256
`a5b8af19a8c4b978f76597aabd53a82d789a10de419dd5c845a90a208208b851` on host
and in Operations. Exact temporary copies and the empty host directory were
removed; absence was confirmed. Container root was used only to set readable
mode and remove the exact root-owned diagnostic copy. No retry, HTTP, jobs,
other-backend cancellation or application/data/configuration changes occurred.
