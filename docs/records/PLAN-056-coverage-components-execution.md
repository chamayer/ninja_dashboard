# PLAN-056 — Coverage component diagnosis

Prepared, approved and executed once 2026-11-10. Task 4 remains open because Coverage timed
out, despite the other ten route pairs completing across the two passes.
The original request's HTTP outcome is unavailable from bounded historical
logs. That is an unresolved failure to diagnose, not accepted performance.

## Concrete next check for approval

On am-ch-01, run the [component collector](../../scripts/diagnostics/plan056_coverage_components.py)
once through Invoke-DevTool.ps1 inside Operations, with its existing runtime
database credentials. One connection, read-only transactions, tenant 1, no
HTTP/login/session, privileged inspection, grants, jobs, config or business
writes. Copy/hash-verify/remove only this file and one fresh host directory.
No application files are changed. No host sampling window or access-log read.

The collector checks the deployed AST fingerprints of `fleet_coverage` and
`current_computer_sql` against locally reviewed HEAD-equivalent functions. Any
mismatch stops before connecting. It reads the deployed source as data, never
executes parsed source, and accepts only literal SQL plus the reviewed lifecycle
fragment. It selects only the eight initial raw HTML SELECTs, excluding CSV
and later page-detail branches, in their actual order:

1. Stored requirements and presence.
2. Hudu inventory with lifecycle/ownership.
3. Current Computer inventory.
4. Client roster.
5. Source presence.
6. Compact source-observation states.
7. Agent platforms.
8. Source-record counts.

Each SELECT runs at most once, with PostgreSQL statement_timeout=3s,
lock_timeout=1s and idle_in_transaction_session_timeout=5s. Stop at the first
error/deadline; no retries or later component queries. Statement timeout
automatically cancels only this probe's own statement, on its known connection;
it does not cancel an application/user/job query. Approval includes that bound.
Output: UTC, labels, own backend PID, elapsed time, aggregate row counts,
exception type/SQLSTATE and connection-closure marker. No SQL text/parameters,
row values, customer identifiers, credentials or exception messages.

Result batches are discarded in memory without logging, with a 100,000-row
processing guard. The guard is not a SQL LIMIT or server memory guarantee;
these are the same reads the page performs before pagination. Total statement
time is bounded by eight 3-second executions, with stop on the first failure.
The in-container timeout terminates only this explicitly launched diagnostic
process, after 60 seconds (kill after a further 5 if necessary). It does not
terminate Gunicorn or another process. Approval includes this process bound.

## Execution after approval

1. Create `/tmp/plan056-coverage-components.XXXXXX` through the helper. SCP the
   one reviewed collector to the same private target and compare full SHA-256.
   Confirm `/tmp/plan056_coverage_components.py` is absent in Operations and
   `/usr/bin/timeout` is executable there; abort rather than overwrite or use
   a fallback. Copy the collector to that exact container path and verify hash.
2. Via the helper run once:

   ```sh
   timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_coverage_components.py
   ```

   Overall setup/execution/cleanup budget: five minutes, no retries. A normal
   probe_finished marker confirms closure of its connection even on a measured
   SQL failure. If the outer wrapper fails without that marker or confirmed
   inner-timeout termination, record incomplete execution rather than asserting
   cleanup or rerunning. No cancellation of other work or permissions fallback.
3. Preserve aggregate results. Hash-check/remove the one copied container file
   and one host file; rmdir the empty host directory and confirm absence.
   Container root is allowed only to remove that root-owned temporary file.

## Interpretation and next branch

A timeout identifies a specific probe query and enforced deadline; SQLSTATE
distinguishes statement cancellation from lock unavailability. It is a lower
bound on that component under current conditions, not a completed query timing
or proof of the historical request's backend. Successful component times include
transaction setup/result consumption and exclude HTTP, ORM policy lookup,
Python inventory assembly, page-detail reads, middleware/context and templates.

This phase tests a concrete frontier. If one SELECT fails, diagnose that exact
query/access path next under its own bounded plan review. If all eight finish,
use their total and individual costs to select the later phases for bounded
tracing; do not declare Coverage healthy or replay it blindly. Cache/load may
differ from the original request. No fleet test on the workstation.

## Local validation

Coverage and selector ASTs match HEAD locally. AST fingerprint gates, exact
eight-query order, CSV/page-detail exclusion, lifecycle interpolation, Python
syntax/import and Ruff/format pass without application setup/database access.
In-memory checks also pass for eight-query success, stop at the first simulated
57014 timeout, connection-context exit, exception-text redaction and source
mismatch before connection. No files were added to the test suite.
No test files or application edits. Deployed-source compatibility, live SQL
and in-container timeout availability are unverified and must fail closed.
Collector SHA-256: `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.
Registry/whitespace checks pass.

## Execution outcome

Deployed AST gates passed. At 14:55:26.837 UTC the first component began;
stored requirements completed in 0.604 s with 19,037 rows. The second component,
Hudu inventory/lifecycle, hit the 3-second server statement deadline: 3.012 s
observed, QueryCanceled/57014 at 14:55:30.453 UTC. This is incomplete, not its
completed runtime. No remaining component was attempted. probe_finished
confirmed connection closure; exit 1 was the measured SQL failure, not an outer
or inner process timeout. No HTTP request or other-work cancellation.

Both copies matched reviewed SHA-256 before execution/removal. Exact container
and host file removed, empty directory removed and absence confirmed. Existing
runtime role used throughout; container root only removed its temporary file.
Next: the separately gated [one-plan check](PLAN-056-coverage-plan-execution.md)
for this exact Hudu SELECT. No repeat of the component pass is authorized.
