# PLAN-056 — Full task 4 measurement pass

Prepared 2026-11-09 after successful authentication/completion pilot. User then
instructed proceeding; pass executed once and stopped at Coverage timeout after
eight successful GETs. See the evidence record below; task 4 remains open.
This is the concrete main pass under PLAN-056, not a new plan.
Supersedes the task 4 draft matrix where different. See the
[pilot/GET audit](PLAN-056-task4-execution.md) and
[evidence record](PLAN-056-platform-performance-assessment.md).

## Exact requested scope

One normal configured-admin login from mounted credentials, at most 22 sequential
GETs (two per route, in order below), logout, overlapping passive observation,
redacted completion-log reads and temporary-file transfer/cleanup on the existing
am-ch-01 production target. Normal login updates last_login and creates a session;
Issues GET may save grouping preferences in that session. These housekeeping
effects are included. No business changes, jobs, refreshes, grants, deployment,
configuration changes, cancellation, new user or synthetic session.

| Order | GET route, initial then immediate repeat |
| --- | --- |
| 1 | `/admin/settings/` |
| 2 | `/` |
| 3 | `/orgs/all/` |
| 4 | `/devices/` |
| 5 | `/inventory/computers/` |
| 6 | `/findings/` |
| 7 | `/sources/` |
| 8 | `/inventory/source-records/` |
| 9 | `/software/` |
| 10 | `/patching/` |
| 11 | `/admin/jobs/?refresh=off` |

Default filters/order/first page, no CSV, search, identifiers or action parameters.
No other role or variants. First/repeat are not claims of cold/hit state; workers
and background workload may differ. Internal loopback port 3002 excludes browser
rendering and external network. Returned HTML/JavaScript is not executed.

## Artifacts and behavior

- [HTTP matrix](../../scripts/diagnostics/plan056_http_matrix.py) contains the
  fixed route list, one 20-second signal deadline per GET, byte counting without
  content output, and first/repeat/UTC/marker/status/timing results. No redirects
  followed. Stop on the first non-200, timeout, SQL error or observer-stop flag;
  only snapshot/logout housekeeping follows, never another page GET.
- [Authentication helper](../../scripts/diagnostics/plan056_http_pilot.py)
  retains the demonstrated normal-login/logout implementation, now with a
  matrix callback. Loads mounted credentials in memory, never prints them.
  Password bootstrap and user enumeration remain excluded.
- [SQL helper](../../scripts/diagnostics/plan056_db_observe.py) supplies only its
  bounded read-only query wrapper; task 3 metadata/sampling main is not invoked.
  Matrix takes at most 44 SQL snapshots (one before/after each GET), with one
  runtime-role connection, tenant 1, 3-second statement/1-second lock/5-second
  idle limits. Snapshot timing is outside HTTP timing. No exception messages.
- Each SQL snapshot returns database counters and at most 20 running/queued
  jobs requested within 24 hours, prioritizing running then newest. No old
  stalled rows, request payloads, scope IDs, customer identifiers, query text or
  raw error/log fields. This misses older running work and may be truncated;
  runtime role still cannot inspect other sessions' waits/query details.
- [Host wrapper](../../scripts/diagnostics/plan056_matrix_host.sh) samples
  CPU, memory/swap, physical-device disk counters and four named Ninja container
  stats every 15 seconds for at most 49 snapshots. It runs one HTTP collector
  with a 720-second wrapper limit; the sampler exits when the collector ends,
  with at most one sampling interval of shutdown delay. Observer failure sets
  one temporary container stop flag checked before each next GET. An in-flight
  request is not canceled. Host sampling emits no unknown container names.
- [Completion filter](../../scripts/diagnostics/plan056_matrix_completion.sh)
  reads at most 10,000 Operations log lines from the last 15 minutes, returning
  only the exact random run prefix/request indices and HTTP status. It emits no
  raw logs. No query/backend attribution is inferred from timestamps.

## Run sequence after approval

1. Create a fresh `/tmp/plan056-task4matrix.XXXXXX` directory through the helper.
   Transfer only these five reviewed files using the same private SSH target;
   compare SHA-256 before execution. Confirm the three container Python paths
   and `/tmp/plan056-task4-stop` are absent; abort rather than overwrite.
2. Copy the three Python files to `/tmp/` in ninja-operations and verify hashes.
   Do not change privileges, images, settings or application files. Via
   Invoke-DevTool.ps1 invoke only:

   ```sh
   timeout 840 sh /tmp/<exact-created-directory>/plan056_matrix_host.sh
   ```

3. Save the already-redacted output in a machine-local temporary capture so
   tool output limits do not lose evidence. Parse compact page/resource results
   locally; do not return credentials, HTML or raw server logs. Overall remote
   setup/observation/completion review remains capped at 15 minutes; no retries.
4. Run completion filter once with emitted 32-hex matrix prefix. Compare observed
   markers/statuses against attempted requests. If a timed-out request lacks
   completion, wait at most 70 seconds, then one final bounded filter invocation;
   no new GET, worker kill, job/SQL cancellation or claimed server deadline.
5. Verify collector/sampler completion. A wrapper timeout is not proof of remote
   completion; report uncertainty and leave cleanup pending if necessary. Normal
   completion includes matrix wrapper exit, database connection closure and
   logout confirmation. Report any failed logout/session cleanup explicitly.
6. Hash-check/remove only the three copied Python files, any known stop flag,
   five host files and observer.done; remove the now-empty host directory with
   rmdir. Container root is permitted only to remove root-owned temporary files,
   not for database queries. Confirm absence. No recursive/wildcard deletion.
   Remove the local capture only after preserving aggregate evidence.

## Results and acceptance limits

Report each attempted route pair, HTTP outcomes, TTFB/complete time, response
size, exact completion coverage and role/cache/endpoint limits. Include aligned
host samples and before/after global database counters plus sampled job keys.
These deltas include concurrent users/jobs/observation, not solely that request.
Do not equate Postgres buffer reads with physical I/O; do not divide aggregate
CPU by guessed core count. No percentiles, load capacity or cold acceptance
claim from one pair. Unattempted pages after stop remain gaps, not successes.
This pass does not waive agreed Home targets or authorize remediation.

## Local validation

Python AST/import/route-bound checks, Ruff/format, Git Bash syntax and a synthetic
log redaction/completion check passed without external access. No test files or
application edits. Registry and whitespace validation pass. Runtime SQL matrix
compatibility and the full request sequence remain untested; the prior pilot
validated normal auth/Settings/log completion only. Subsequent run: eight 200s,
Coverage client timeout, logout and diagnostic cleanup confirmed; Coverage server
completion unverified. Next: bounded monitoring-path review, not a replay.
