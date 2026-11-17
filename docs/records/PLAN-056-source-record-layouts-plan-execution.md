# PLAN-056 — Source Records layout-facet plan check

Prepared 2026-11-10 after the approved entity-type facet plan. This is the next
unmeasured reader component from the bounded Source Records frontier.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact distinct nonnull `observation.source_layout`
choices SELECT from `source_records`, on am-ch-01 through `Invoke-DevTool.ps1`,
inside Operations using the existing runtime database role. One connection,
tenant 1, read-only transaction, 3-second statement, 1-second lock and 5-second
idle-transaction deadlines. The population is the default tenant and record-kind
subject scope, with the query's existing `source_layout IS NOT NULL` condition;
no source, client, search or other filters. No facet-query execution,
HTTP/auth/session, Jobs, other SQL, retries, alternate roles, grants,
schema/config changes, cache flush or fixes.

The collector verifies the reviewed `source_records` AST and exact selected SQL
plus tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, customer identifiers, credentials and exception messages. Plan
estimates are not actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_source_record_layouts_plan.py),
  SHA-256 `6e595f08307e5baacde502e7c53c8b754d907c9ced6e31e9c96704f6071183c0`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-source-record-layouts-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_source_record_layouts_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_record_layouts_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 633-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `source_records` AST gate passed; own backend PID 354225. The
non-ANALYZE plan completed at 16:43:10.983 UTC in 0.118 s, nine nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Sort | 200 | 32 | 172204.83 | 172205.33 |
| 1 / 0 | Aggregate | 200 | 32 | 172195.18 | 172197.18 |
| 2 / 1 | Result | 41047 | 32 | 14587.09 | 172092.57 |
| 3 / 2 | Hash semi-join | 41047 | 32 | 14587.09 | 172092.57 |
| 4 / 3 | Result | 82094 | 1710 | 5504.01 | 161516.40 |
| 5 / 4 | Bitmap heap scan, entity_observation_current | 82094 | 694 | 5504.01 | 160900.70 |
| 6 / 5 | Bitmap index scan, uq_obs_current_tenant_observation | 82507 | 0 | 0 | 5483.22 |
| 7 / 3 | Hash | 35057 | 24 | 8644.85 | 8644.85 |
| 8 / 7 | Seq scan, source_record_subjects | 35057 | 24 | 0 | 8644.85 |

This has the same estimated broad tenant observation scan, subject semi-join,
distinct aggregate and sort as the entity-type facet. The layout query's
non-null filter changes estimated rows only slightly; it still uses heap access
to read `source_layout`. Estimated total cost 172205.33 is planner cost, not
elapsed time or an actual comparison. Task 5 remains partial. Next: obtain
approval for the prepared client-choice plan check; no client-choice execution
or fix is approved.
