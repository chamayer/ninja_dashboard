# PLAN-056 next three Home reader checks

## Approved scope — 2026-11-10

User approved the next three Home reader checks. This pass measures exactly
Coverage, Software, then Sources once each, in Home order, through direct reader
calls on `am-ch-01` inside Operations with the existing application database
role. The preceding Patching failure is not repeated; Jobs is outside this
three-check approval.

One tenant-1 repeatable-read/read-only transaction; 3-second per-statement,
1-second lock, 5-second idle-transaction limits, and 60-second process limit.
Stop on first error or source mismatch. Discard all return values. Emit only
UTC, own backend PID, component timing, error class/SQLSTATE and connection
closure. No HTTP/session/template, retry, cache flush, query cancellation,
other-session inspection, job execution, role/grant/schema/config/data change,
or application fix.

The collector pins deployed source hashes for `coverage_reads.py`,
`computer_reads.py`, `software_review.py` and `views.py`; the values were
validated by the immediately prior approved Home reader pass. It also confirms
one interpolated query in `coverage_reads.home_summary()`. Any source drift
stops before database access.

Reviewed collector: [plan056_home_next_three.py](../../scripts/diagnostics/plan056_home_next_three.py).
After local syntax/hash review, transfer only this `.py` file by SCP. The SSH
session's private `/tmp` is ephemeral between invocations, so stage it in the
account home, then in one helper invocation create a fresh private
`/tmp/plan056-home-next-three.XXXXXX`, verify the local-staging hash, install
the exact file, verify its hash, copy it into Operations, set readable mode,
and verify the container hash before running once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_home_next_three.py
```

The same helper invocation must hash-check and remove only the exact temporary
host/container files, remove the empty private directory, and confirm absence.
Container root is used only for mode adjustment and exact diagnostic cleanup.
Five-minute setup/execution/cleanup budget. If process/connection closure is
not confirmed, report unresolved and do not retry.

## Local preparation checks

Collector syntax parsing passed; AST inspection found exactly one interpolated
main query in local `coverage_reads.home_summary()`. Local `coverage_reads.py`
matches its pinned runtime hash; local `computer_reads.py` differs from the
runtime pin, so only the runtime gate can establish target compatibility. No
external access or tests were performed during preparation.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on
`am-ch-01`; all four source hash gates passed. Own backend PID 359974. Coverage
completed in 0.254 s. Software then hit the 3-second statement timeout at
3.010 s (`OperationalError/57014`); Sources was not attempted. The collector
stopped and confirmed connection closure. Exit status was 1 for the bounded
statement failure. Both exact host/container copies matched SHA-256
`9c07da73f57598020c9e76734083dd73068b49ee687441fd92354ba5dcfaf92c`; they and
the empty host directory were removed and absence confirmed. No retries, HTTP,
jobs, other-session cancellation, or application/data/configuration changes.

The 0.254-second Coverage reader result is one direct-reader measurement, not
Home response time. The Software timeout attributes a deadline to its single
Home summary reader, not an internal node or execution cause. No remedy is
selected. A separate plan-only approval is required before planner diagnosis.
