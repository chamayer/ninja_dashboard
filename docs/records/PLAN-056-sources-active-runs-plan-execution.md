# PLAN-056 — Sources active-run plan check

Prepared 2026-11-10 as the next query in the Sources read frontier. Earlier
component execution stopped at `v_source_instance_record_counts` after its
3-second deadline; later components were intentionally not attempted.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the active source-refresh Jobs SELECT from
`sources_status`, on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations
using the existing runtime database role. One connection, tenant 1, read-only
transaction, 3-second statement, 1-second lock and 5-second idle-transaction
deadlines. It selects only queued/running `source-refresh` job rows scoped to
the tenant. No query execution, HTTP/auth/session, Jobs activity or mutation,
other SQL, retries, alternate roles, grants, schema/config changes, cache flush
or fixes.

The collector verifies the reviewed `sources_status` AST and exact selected SQL
plus tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, scope IDs, credentials and exception messages. Estimates are not
actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_sources_active_runs_plan.py),
  SHA-256 `34f734cb271d781afa028cbe6d88dea23d3bf21a4e682ea85f315eda6c7e8692`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-sources-active-runs-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_sources_active_runs_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_sources_active_runs_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 317-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `sources_status` AST gate passed; own backend PID 355037. The
non-ANALYZE plan completed at 16:58:35.031 UTC in 0.034 s, two nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and the empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Result | 1 | 57 | 0.41 | 16.95 |
| 1 / 0 | Index scan, operator_job_runs / idx_operator_job_runs_status | 1 | 55 | 0.41 | 16.95 |

The active queued/running source-refresh query has a direct index-scan path in
the estimate. Cost 16.95 is planner units, not runtime. Task 5 remains partial.
Next: prepare the plan for latest source-refresh run per binding. No query
execution, additional Jobs inspection or fix is approved.
