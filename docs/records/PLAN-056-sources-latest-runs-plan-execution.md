# PLAN-056 — Sources latest-run plan check

Prepared 2026-11-10 after the approved active-run query plan. The original
bounded Sources pass stopped at record counts; this is the next unmeasured
Sources history SELECT.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact latest source-refresh run per binding
SELECT from `sources_status`, on am-ch-01 through `Invoke-DevTool.ps1`, inside
Operations using the existing runtime database role. One connection, tenant 1,
read-only transaction, 3-second statement, 1-second lock and 5-second idle-
transaction deadlines. It selects the most recently requested source-refresh
run per binding for the tenant. No query execution, HTTP/auth/session, Jobs
activity or mutation, other SQL, retries, alternate roles, grants,
schema/config changes, cache flush or fixes.

The collector verifies the reviewed `sources_status` AST and exact selected SQL
plus tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, scope IDs, credentials and exception messages. Estimates are not
actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_sources_latest_runs_plan.py),
  SHA-256 `cb15bce78556f836e5e45e85f2003c668bcf81079ada0291d92f4eac007e6a12`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-sources-latest-runs-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_sources_latest_runs_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_sources_latest_runs_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 490-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `sources_status` AST gate passed; own backend PID 355213. The
non-ANALYZE plan completed at 17:01:04.429 UTC in 0.028 s, four nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and the empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Unique | 18 | 78 | 12890.69 | 12905.18 |
| 1 / 0 | Sort | 2898 | 78 | 12890.69 | 12897.93 |
| 2 / 1 | Result | 2898 | 78 | 0.01 | 12724.04 |
| 3 / 2 | Seq scan, operator_job_runs | 2898 | 76 | 0.01 | 12702.31 |

The latest-run-per-binding query is estimated to scan source-refresh run rows,
sort by the computed binding identity/request time, then unique. Estimated cost
is planner units, not runtime. Task 5 remains partial. Next: prepare the final
Sources read-frontier check, recent 30 source-refresh runs; no query execution
or fix is approved.
