# PLAN-056 — Sources recent-run plan check

Prepared 2026-11-10 after the latest-run-per-binding plan. This is the final
SELECT in the reviewed Sources component frontier; the historical listing is
limited to the latest 30 source-refresh runs.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact recent-30 source-refresh run SELECT from
`sources_status`, on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations
using the existing runtime database role. One connection, tenant 1, read-only
transaction, 3-second statement, 1-second lock and 5-second idle-transaction
deadlines. It joins the run to its binding, instance and source, orders by
completion/start/request time, and applies the existing `LIMIT 30`. No query
execution, HTTP/auth/session, Jobs activity or mutation, other SQL, retries,
alternate roles, grants, schema/config changes, cache flush or fixes.

The collector verifies the reviewed `sources_status` AST and exact selected SQL
plus tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, source/run identifiers, credentials and exception messages.
Estimates are not actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_sources_recent_runs_plan.py),
  SHA-256 `931098aa513adeec78669d26b6b392c7803b2202f19b8e61cfe25f845483ede1`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-sources-recent-runs-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_sources_recent_runs_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_sources_recent_runs_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 868-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `sources_status` AST gate passed; own backend PID 355859. The
non-ANALYZE plan completed at 17:13:49.002 UTC in 0.034 s, ten nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and empty host directory were removed and absence
confirmed.

The visible plan shape is a sequential scan of `operator_job_runs` beneath
nested-loop joins to bindings, instances and sources, followed by a sort and
limit. The run scan's estimated total cost is 12963.61; top estimated cost is
13077.20 planner units, not elapsed time. The query's LIMIT 30 does not avoid
the estimated history scan and sort. Task 5 remains partial; the Sources SQL
frontier has been mapped. Next: trace the still-unmeasured Source Records page
row query and prepare one bounded plan check. No row execution or fix is
approved.
