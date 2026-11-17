# PLAN-056 — Sources and Source Records read attribution

Prepared and executed once 2026-11-10 after the user's instruction to proceed.
First task 5 measurement frontier after the
[local read map](PLAN-056-read-attribution.md). Sources took 11.661/10.413 s and
Source Records 13.358/14.142 s in task 4; this pass attributes selected SQL, not
the complete HTTP response. No fixes or benchmark loop.

## Exact scope for approval

One pass on am-ch-01 through Invoke-DevTool.ps1 inside Operations, using the
existing runtime database role. One connection, tenant 1, read-only transactions,
at most nine SELECTs in this order:

| Order | Exact existing default-reader component |
| --- | --- |
| 1 | Sources health/binding rows from v_source_instance_health |
| 2 | Sources per-instance/type rows from v_source_instance_record_counts |
| 3 | Active queued/running source-refresh Jobs |
| 4 | Latest source-refresh run per binding |
| 5 | Latest 30 source-refresh runs |
| 6 | Unfiltered Source Records matching count through masked admin metadata, requiring a record-kind subject |
| 7 | Source Records distinct type choices for the same record population |
| 8 | Source Records distinct nonnull layout choices for that population |
| 9 | Source Records nondeleted client-choice rows (three-column projection) |

The last read is not the wider navigation Client ORM read. Source Records row
page/enrichment, shared badges, Home, Software and Patching are not executed.
No HTTP/auth/session effects, jobs, resource window, logs, privileged inspection,
new instrumentation, grants, schema/index/config/app changes or candidate fixes.

Each SELECT runs once with a 3-second PostgreSQL statement deadline, 1-second
lock deadline and 5-second idle-transaction deadline. Stop at the first error,
deadline or 100,000-row client processing bound; no retry or later component.
Approval includes automatic cancellation only of this diagnostic's own
statement on that connection and timeout termination only of the diagnostic
process. A timeout is an incomplete result, not a completed timing or proof of
a lock/CPU cause. Different snapshots/concurrent load/cache may affect reads;
do not sum them into a task 4 HTTP breakdown.

## Exact artifacts and output

- [Read collector](../../scripts/diagnostics/plan056_source_reads.py).
- [Unchanged component helper](../../scripts/diagnostics/plan056_coverage_components.py),
  imported for AST fingerprints/function extraction/aggregate emission only.
  None of its Coverage/database main logic is run.

Collector verifies deployed sources_status/source_records ASTs against reviewed
HEAD-equivalent functions before connecting. Sources literals retain their
original order. The Source Records count uses exactly its two default clauses,
without filter parameters; type/layout/client choices are the existing SQL.
Every selected statement must be SELECT with one tenant placeholder. No parsed
source is executed. Source or query-shape mismatch stops before connecting.

Only UTC, own backend PID, component label, elapsed time, aggregate result-row
count, exception class/SQLSTATE and connection-closure marker are returned.
Credentials, query text/parameters, IDs, names, raw error fields, customer data
and exception messages are not emitted. Existing Sources SELECTs include error
and identity columns; result batches are counted/discarded in memory, never
printed or saved. The client row guard is not a SQL memory/work guarantee.

## Execution after approval

1. Create `/tmp/plan056-source-reads.XXXXXX` via the shared helper; SCP only the
   two exact reviewed files to the same private target and compare full SHA-256.
   Confirm `/tmp/plan056_source_reads.py` and
   `/tmp/plan056_coverage_components.py` are absent in Operations and
   `/usr/bin/timeout` is executable; abort rather than overwrite or fall back.
   Copy both files to those exact container paths and verify hashes.
2. Through the helper invoke once:

   ```sh
   timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_reads.py
   ```

   Five-minute overall setup/execution/cleanup budget. Inner termination applies
   only to the explicitly launched process after 60 seconds, kill after 5 more;
   no Gunicorn/worker termination. read_probe_finished confirms connection
   closure, including a measured SQL failure. Missing closure without confirmed
   inner termination means incomplete execution; do not retry/cancel other work
   or claim cleanup while execution may continue.
3. Preserve aggregates; hash-check/remove only the two container and two host
   files, then rmdir the empty directory and confirm absence. Container root
   may remove only root-owned diagnostic copies, never query the database.
   No wildcard/recursive deletion or changes to existing application files.

## Local validation and gate

ASTs match HEAD locally. Import/AST, exact nine-component selection/order,
tenant placeholder/default population, and in-memory success, timeout stop,
source mismatch, redaction and connection-exit checks pass. Ruff/format,
registry and whitespace checks pass. No test files or app edits; no new
production access during preparation. Live compatibility/results are unverified.

Collector SHA-256:
`49dbfe07724ca36f49eeb4e351018ddcb3625af9fdb65d30a99388c9d61b26b4`.
Unchanged helper SHA-256:
`39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.
## Execution outcome — 2026-11-10

User instructed `next` in response to the concrete approval request for this
exact pass. Executed once through the shared helper with the existing runtime
role; both deployed reader AST gates passed. Own backend 351640.

| Component | Outcome |
| --- | --- |
| sources_health | Completed in 0.643 s, 17 result rows |
| sources_record_counts | QueryCanceled/57014 at its 3-second server deadline, observed 3.008 s; incomplete |
| Remaining seven components | Not attempted under stop-on-first-failure |

Collection ran 15:48:19.419–15:48:23.071 UTC. read_probe_finished confirmed
connection closure, one completed component and status 1. Exit 1 was the
measured query failure; neither wrapper deadline was reached. No retry, later
SELECT, HTTP, session, job, privilege/schema/config change or other-work
cancellation. Server cancellation applied only to this probe's own statement.

Both host/container files matched reviewed full SHA-256 before execution and
removal. Exact copies and empty host directory removed; absence confirmed.
Container root was used only for temporary-file removal. No raw rows, errors,
credentials or query text were returned. Registry/whitespace checks pass.

This isolates a slow Sources component, not its complete HTTP cost or the
specific operation inside the view. Companion-stream predicate/grouping remains
a code-level lead, not measured internal attribution. A 57014 result does not
establish absence of every kind of wait. Source Records components and the
remaining Sources history queries are still unmeasured.

Next: fresh session, verify Git/checkpoint, prepare a bounded non-ANALYZE plan
check of this exact record-count SELECT and obtain explicit execution approval.
No repeat or skip-ahead continuation is authorized by this completed pass.
Task 5 remains incomplete; no fixes authorized.
