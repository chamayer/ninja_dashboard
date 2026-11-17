# PLAN-056 Home Software summary plan-only diagnostic

## Proposed bounded protocol

Prepared after the approved Home reader pass attributed a 3.010-second
statement deadline to Software. Two invocations stopped at the collector's
query-shape gate before opening a database connection. The corrected invocation
subsequently completed under the user's existing authorization.

One non-ANALYZE EXPLAIN of the exact Home installed-title aggregate, on
`am-ch-01` inside Operations with the existing application database role. The
collector calls `software_review.home_summary()` once under tenant 1 in a
repeatable-read/read-only transaction, intercepts its single main statement,
and replaces it with `EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` using the
same SQL and parameters. It returns an in-process empty result set only so the
reader can finish; the aggregate itself is not executed.

Limits: 3-second statement timeout, 1-second lock timeout, 5-second idle
transaction timeout, and 60-second process limit. Stop on source/query-shape
mismatch, first error, missing plan or timeout. Output is limited to UTC, own
backend PID, elapsed planning time, at most 120 allowlisted plan-node fields,
error class/SQLSTATE and closure. No SQL/expressions, filters, values, HTTP,
session, other readers, retry, cache flush, job, cancellation, other-session
inspection, role/grant/schema/config/data change or application fix.

The runtime SHA-256 gates pin `software_review.py` and `computer_reads.py` to
the exact versions that passed the immediately preceding approved three-reader
pass. An AST gate requires one interpolated `home_summary()` query beginning
with `title_publishers` and five reviewed substitutions in order:
`current_computer_sql("d")`, `TITLE_STATUS_CTES`,
`current_computer_sql("device")`, `TITLE_STATUS`, and `TITLE_STATUS_JOINS`.
A mismatch stops before database access.

Corrected collector: [plan056_home_software_plan.py](../../scripts/diagnostics/plan056_home_software_plan.py),
SHA-256 `86d40d65c069386dd0f50f12034670b09d6d234757595bff6da370e8a685f0da`.
Both invocations passed the deployed source hashes but rejected the query
shape before database access. The deployed `software_review.py` is the full
title-status query from local commit `60ba6e45`; the current uncommitted
worktree has a simplified count query. The earlier gate assumed the working
copy shape. The corrected gate passed locally against the exact historical
source whose SHA-256 matches the deployed pin. Both failed invocations
confirmed exact temporary cleanup. The five-check sequence stopped at its
first check as specified; the remaining four were not run. The user's five-check
authorization persists; earlier requests for repeated approval were unnecessary.
For the authorized invocation, SCP the exact
collector to private SSH staging, then in one helper invocation create a fresh
private `/tmp/plan056-home-software-plan.XXXXXX`, verify/install the staged
hash, copy to the exact Operations path, set readable mode, verify the
container hash and invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_home_software_plan.py
```

The same invocation hash-checks and removes only the exact temporary files,
removes the empty private directory, and confirms absence. Container root is
used only for file mode and exact cleanup. Five-minute setup/execution/cleanup
budget. Missing closure without confirmed process termination leaves the
operation unresolved; no retry or cancellation of another backend.

## Confirmed outcome — 2026-11-10

Local verification used both historical files from `60ba6e45`, whose byte
hashes match the runtime pins. It exercised the complete historical function,
SQL interpolation, interception and synthetic `fetchall()` with a fake cursor:
exactly one EXPLAIN was issued and the business query was never sent to that
cursor. No Django setup or database was used in this local verification.

The subsequent remote invocation passed both source hashes and the corrected
AST gate. Backend 361850; non-ANALYZE planning completed in 0.178 s, with 56
nodes and `truncated=false`. Status 0 and connection closure were confirmed.
The tool display clipped the node list; only visible metadata is retained.
Root Aggregate cost is estimated at 165452.77, with 9537 estimated output rows.
A visible title-grouping/sorting branch estimates 63082 groups and a Gather
Merge of 126164 rows. These estimates describe planning choices, not actual
rows, execution time or the cause of the reader timeout.

Host/container hashes matched the reviewed collector before removal. Exact
files and empty private directory were removed and absence confirmed. No
business aggregation, HTTP, session or Jobs execution occurred. Check 1 of the
authorized five is complete; Sources, Jobs and cold/warm Home brand context
checks remain authorized and unattempted.
