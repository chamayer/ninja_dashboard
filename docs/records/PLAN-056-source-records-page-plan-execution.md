# PLAN-056 — Source Records default page-row plan check

Prepared 2026-11-10 after mapping the Sources query frontier. This check
targets the still-unmeasured Source Records page SELECT that follows its count
and global facets.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact default Source Records page-row SELECT from
`source_records`, on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations
using the existing runtime database role. One connection, tenant 1, read-only
transaction, 3-second statement, 1-second lock and 5-second idle-transaction
deadlines. Default page 1, page size 100, tenant and record-kind subject clauses
only; no source/client/search/state/type/layout/reason/relationship filters.
The plan preserves the existing materialized page and group-mapping CTEs,
relationship joins, order and four bound parameters `(tenant, 100, 0, tenant)`.
No row-query execution, count/facet query, HTTP/auth/session, Jobs, other SQL,
retries, alternate roles, grants, schema/config changes, cache flush or fixes.

The collector verifies the reviewed `source_records` AST, exact default
population, SQL interpolation constants, page-limit substitution and parameter
shape before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, customer identifiers, credentials and exception messages. Plan
estimates are not actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_source_records_page_plan.py),
  SHA-256 `90b6a4992885e6b6e69734e8f8a56534966856a6c0644dcbcc520e3fd833b2af`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-source-records-page-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_source_records_page_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_records_page_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local AST gate passed. The collector reconstructs the default 4,357-character
page SELECT, verifies four placeholders and the parameter expression, and
passes Python syntax parsing. No external access or application/test changes.
**Next:** obtain explicit approval for this exact plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `source_records` AST gate passed; own backend PID 356234. The
non-ANALYZE plan completed at 17:21:56.441 UTC in 0.180 s. The collector
reported `truncated: false` and `plan_finished` status 0; connection closure
confirmed. The local tool display truncated the large JSON node list, so only
visible summary findings are retained; no retry was made. Host/container hashes
matched the reviewed collector and unchanged helper before removal; exact
copies and empty host directory were removed and absence confirmed.

Visible plan summary: root Sort estimated total cost 211565.73. Its default
page CTE estimates a sort of 41,254 candidates at cost 190,705.22, with a
bitmap heap scan of tenant observations (82,507 estimated rows, cost
160,281.73) joined to record subjects (sequential scan/hash, 35,057 estimated
rows, cost 8,644.85). The page then applies the 100-row limit. The separately
materialized client-source group mapping has estimated cost about 20,613.24.
These are planner units and estimated cardinalities, not measured runtime or
actual loop counts. The visible plan supports broad candidate ordering and
mapping work as leads; the hidden remainder prevents complete node-by-node
attribution. The separately approved page-row SELECT subsequently hit its
3-second deadline at 3.009 s (`QueryCanceled/57014`) with zero rows returned.
This confirms a slow component but does not assign cost to a node/function. See
the [bounded read outcome](PLAN-056-source-records-page-read-execution.md).
Task 5 remains partial; no retry, `EXPLAIN ANALYZE`, broader timeout or fix is
approved.
