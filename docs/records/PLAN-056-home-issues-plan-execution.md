# PLAN-056 — Home Issues query plan

Prepared 2026-11-10 after the approved Home reader pass attributed a 3-second
statement deadline to the Issues summary/attention component. This plan check
does not execute the aggregation or establish its runtime.

## Exact scope

One non-ANALYZE EXPLAIN on am-ch-01 through `Invoke-DevTool.ps1`, inside
Operations, using the existing runtime database role. One tenant-1 read-only
repeatable-read transaction, with 3-second statement, 1-second lock and
5-second idle-transaction deadlines. The collector performs the small finding
type-registry SELECT needed by the real `mapping_types()` call, constructs the
same `home_data()` query through `_filtered_sql(Scope(status="open_paused"),
summary=True, home_compact=True)`, extracts the exact SQL suffix from the
reviewed deployed `home_data()` AST, and issues one
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)`.

It does not run the aggregation, fetch any finding or candidate rows, issue
HTTP/auth/session requests, run Jobs, inspect other sessions, enable
instrumentation, retry, use another role, alter grants/schema/config/data, or
change application code. A plan timeout is incomplete planner evidence, not an
execution time or proof of a lock/CPU cause.

Before connecting, the collector checks SHA-256 of deployed `issue_selection.py`
and `finding_registry.py` against HEAD `ca00938a`, and verifies that
`home_data()` contains exactly one `cursor.execute(sql + <literal suffix>,
params)` call. Mismatch stops without connecting. Output includes only phase,
elapsed time, own backend PID, SQLSTATE/error class, closure marker and at most
120 plan nodes with allowlisted planner metadata: node/parent/type, schema and
relation name, index/function/CTE name, cost, estimated rows/width and parallel
flag. It excludes SQL, expressions, filters, parameters, row values, query text,
credentials and exception messages.

Reviewed artifacts:

- [Collector](../../scripts/diagnostics/plan056_home_issues_plan.py), SHA-256
  `dbede3f6c70580a05a2e67edb4415047af6c0380c12f862f2bfdcb55dba1333e`.
- [Unchanged output helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

## Execution procedure and approval

User approved one bounded Home Issues attribution step after the scope was
explained. Create a fresh private host directory
`/tmp/plan056-home-issues-plan.XXXXXX`; verify both hashes, confirm exact
Operations destinations `/tmp/plan056_home_issues_plan.py` and
`/tmp/plan056_coverage_components.py` are absent, and ensure
`/usr/bin/timeout` is executable. Copy only those files and hash-check both
host and container copies. Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_home_issues_plan.py
```

Five-minute setup/execution/cleanup budget. Stop on mismatch, timeout or error;
no retry. Preserve sanitized output. After confirmed completion/failure,
hash-check and remove only the exact files, remove the empty host directory,
and confirm absence. If connection closure is missing without confirmed process
termination, leave the operation unresolved and do not cancel other work.

## Preparation checks

Local AST extraction from `git show HEAD:operations/apps/core/issue_selection.py`
found one reviewed query suffix of 4,287 characters. Collector syntax parsing
passed. No external access or application/test changes were made in preparation.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through the shared helper on verified
`am-ch-01`. Both deployed source hashes passed; own backend PID 358449. The
finding-type registry lookup and exact Home `home_data()` query construction
completed, followed by one non-ANALYZE EXPLAIN. Planning completed in 0.185 s;
the collector emitted 59 nodes with `truncated=false`, then confirmed
`plan_finished status=0 connection_closed=true`. No rows from the aggregation
were executed or returned. No retries, HTTP, Jobs, other-backend cancellation
or application/data/configuration changes occurred.

The tool display clipped the serialized node list despite the collector
returning all 59 nodes; retain only visible fields. The root is an `Append`,
estimated 6,369 rows, total cost 103,658.72 planner units. A visible findings
branch estimates a 54,825-row bitmap heap scan using
`idx_findings_status_severity` (cost 65,167.26), with finding-type hash join
and multiple aggregate/unique branches. These are estimates, not actual row
counts, loop counts, statement time or per-node contribution. The exact
aggregation plan is now characterized at a high level, but the deadline's
actual runtime cause remains unmeasured.

Both host/container files matched reviewed hashes before execution and after
completion. Exact files and the empty host directory were removed and absence
confirmed; container root was used only for exact temporary cleanup. No retry
or plan variant is authorized. Task 5 remains partial; no fix authorized.
