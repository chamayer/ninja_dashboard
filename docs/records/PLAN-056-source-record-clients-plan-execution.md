# PLAN-056 — Source Records client-choice plan check

Prepared 2026-11-10 after the approved nonnull layout-facet plan. This is the
next unmeasured default reader component.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact Source Records client-choice SELECT from
`source_records`, on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations
using the existing runtime database role. One connection, tenant 1, read-only
transaction, 3-second statement, 1-second lock and 5-second idle-transaction
deadlines. It selects only `id`, `slug` and `display_name` from nondeleted
tenant clients, ordered by display name. No client-choice query execution,
HTTP/auth/session, Jobs, other SQL, retries, alternate roles, grants,
schema/config changes, cache flush or fixes.

The collector verifies the reviewed `source_records` AST and exact selected SQL
plus tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, client identifiers/names, credentials and exception messages. Plan
estimates are not actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_source_record_clients_plan.py),
  SHA-256 `477dad22fd69412edc28b41a1849445ecbc1779a83cc117b30a8c4c7e50156b7`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-source-record-clients-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_source_record_clients_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_record_clients_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 185-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `source_records` AST gate passed; own backend PID 354885. The
non-ANALYZE plan completed at 16:55:31.353 UTC in 0.014 s, three nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Sort | 76 | 36 | 6.33 | 6.52 |
| 1 / 0 | Result | 76 | 36 | 0.01 | 3.96 |
| 2 / 1 | Seq scan, operations.clients | 76 | 36 | 0.01 | 3.96 |

The plan is a small scan of tenant clients followed by ordering. Total estimated
cost 6.52 planner units is not a runtime measurement. Unlike observation-backed
facets, this choice list does not scan observation/subject views. Task 5 remains
partial; next resume the remaining Sources queries from the original bounded
frontier. No page request or query execution is approved.
