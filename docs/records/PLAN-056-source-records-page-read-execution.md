# PLAN-056 — Source Records default page-row read

Prepared 2026-11-10 after the non-ANALYZE page plan. The plan estimates a broad
tenant observation scan, candidate sort and relationship enrichment. This
single read determines whether that exact default page SELECT completes within
the already approved 3-second diagnostic statement bound; it does not measure
HTTP latency or isolate individual plan nodes.

## Exact scope for approval

Execute the exact default first-page Source Records SELECT once, on am-ch-01
through `Invoke-DevTool.ps1`, inside Operations using the existing runtime
database role. One connection, tenant 1, read-only transaction, 3-second server
statement timeout, 1-second lock timeout and 5-second idle-transaction timeout.
Default population only: tenant and record-kind subject, page 1, page size 100,
with existing group mapping and relationship joins. Bound parameters are
`(1, 100, 0, 1)`. No other Source Records count/facet query, HTTP/auth/session,
Jobs, other SQL, retries, alternate roles, grants, schema/config changes, cache
flush or fixes.

The collector verifies the reviewed `source_records` AST, SQL interpolation
constants, default population, limit replacement and parameter expression
before connecting. It executes only that one SELECT; each returned row is
discarded in memory, with at most 100 rows accepted. Output is limited to UTC,
own backend PID, elapsed time, aggregate row count or error class/SQLSTATE, and
connection-closure marker. No SQL, raw rows, identifiers, names, payloads,
exception messages or credentials are emitted or saved. Statement timeout
cancellation applies only to this diagnostic statement. Timeout is incomplete
evidence, not a completed timing. No retry.

Temporary files within this scope:

- [Read collector](../../scripts/diagnostics/plan056_source_records_page_read.py),
  SHA-256 `500cff40d9810373187c140348807eb2fd93ff1905e6d03a46a531ebe04b00e1`.
- [Reviewed page-query extractor](../../scripts/diagnostics/plan056_source_records_page_plan.py),
  SHA-256 `90b6a4992885e6b6e69734e8f8a56534966856a6c0644dcbcc520e3fd833b2af`.
- [Unchanged helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-source-records-page-read.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_source_records_page_read.py`,
`/tmp/plan056_source_records_page_plan.py` and
`/tmp/plan056_coverage_components.py` are absent; confirm `/usr/bin/timeout` is
executable. Copy only these three files and verify hashes. Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_records_page_read.py
```

Five-minute setup/execution/cleanup budget. Preserve sanitized output. On
confirmed completion or failure, hash-check and remove only those exact
container/host files, remove the empty host directory and confirm absence. If
the closure marker is missing without confirmed process termination, leave
execution unresolved and do not cancel other work.

## Preparation checks

Local collector verifies the reviewed AST and reconstructs the exact 4,357-
character page SELECT with four parameters. Syntax parsing passed. No external
access or application/test changes. **Next:** obtain explicit approval for
this one bounded read.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed AST/source/parameter gates passed; own backend PID 356472. The
single default page SELECT hit the 3-second server deadline:
`QueryCanceled/57014`, observed 3.009 s. No rows were returned; the collector
reported row disposal and `read_finished` status 1 with connection closure.
The timeout is incomplete evidence, not a completed query time. No retry or
other query ran.

All three host/container files matched reviewed hashes before removal; exact
copies and the empty host directory were removed and absence confirmed. The
database canceled only this diagnostic's own statement. No HTTP, jobs, other
backend cancellation, data output or application change occurred.

This confirms the default page-row SELECT independently reaches the configured
3-second deadline under this sample. It does not identify which plan branch or
function consumed the time. Combined with the tool-truncated estimate, the
strongest leads remain broad candidate scan/sort and group-mapping work; neither
is measured as a cost share. Task 5 remains partial. Next: preserve this gap and
review alternative diagnostics/requirements in a fresh session; no retry,
`EXPLAIN ANALYZE`, broader timeout or fix is authorized.
