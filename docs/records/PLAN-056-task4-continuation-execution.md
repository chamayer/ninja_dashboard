# PLAN-056 — Task 4 six-page continuation

Prepared, approved and executed once 2026-11-10. Task 4 remains partial. The approved Coverage
completion check found no historical marker and no current Operations-labeled
sessions, leaving its original outcome unknown. Do not replay Coverage, poll
for its past outcome or repeat the four completed page pairs. This separate
window is needed because the main pass stopped before these six pages.

## Exact scope for approval

One pass on am-ch-01 through Invoke-DevTool.ps1: normal configured-admin
login/logout, at most 12 sequential measured GETs, overlapping passive host
observation, at most 24 bounded runtime-role SQL snapshots, completion-log reads,
and temporary transfer/hash verification/cleanup. Normal authentication can
update last_login, create/delete a session and generate logs; Issues may save
grouping preferences in that session. These effects and ordinary session
housekeeping are included. No business changes, jobs, refreshes, grants,
configuration, deployment, cancellation, cache flushing or elevated database
inspection. The prior completion-check approval does not authorize this pass.

| Order | Route: first-observed then immediate repeat |
| --- | --- |
| 1 | `/findings/` |
| 2 | `/sources/` |
| 3 | `/inventory/source-records/` |
| 4 | `/software/` |
| 5 | `/patching/` |
| 6 | `/admin/jobs/?refresh=off` |

Default scope/order/first page, no search, customer IDs, export or actions.
Reuse the selected-GET audit in the [original review](PLAN-056-task4-execution.md).
This preparation changes no application files or GET paths. Mounted credentials
stay in memory inside Operations; no new users, impersonation, synthetic
sessions, password bootstrap or user enumeration. Login's redirect destination
is Settings, but the collector never follows it or fetches Settings. Internal
loopback 3002 excludes browser rendering/external network; no JS/subresources.

## Exact artifacts and bounds

- [HTTP continuation](../../scripts/diagnostics/plan056_http_continuation.py):
  fixed six-route list, two GETs each, 20-second signal deadline per GET;
  random run prefix, UTC, status, header/complete timing and byte count only.
  First failure/non-200/timeout/SQL error/observer flag stops measured GETs;
  only after-snapshot and logout housekeeping follow where possible.
- [Authentication](../../scripts/diagnostics/plan056_http_pilot.py): unchanged
  demonstrated normal login/logout; each network operation has a 20-second
  socket timeout. No redirects, cookies, bodies, secrets or exception text in
  output. Report logout confirmation separately from page/server completion.
- [SQL helper](../../scripts/diagnostics/plan056_db_observe.py): only its
  read-only query wrapper is used; task 3 main is not invoked. One connection,
  tenant 1, 3-second statement/1-second lock/5-second idle limits. At most 24
  snapshots of global counters and 20 recent running/queued jobs requested in
  24 hours; older jobs/truncation and runtime-role visibility remain limitations.
  No query text, payloads or customer identifiers. SQL time is outside HTTP time.
- [Host wrapper](../../scripts/diagnostics/plan056_continuation_host.sh): fresh
  `/tmp/plan056-task4continuation.XXXXXX` directory, at most 33 samples every
  15 seconds, 480-second collector wrapper. Samples CPU/memory/swap/disk
  counters and only the same four named containers. Stops sampler when collector
  ends, waits for it, emits wrapper exit. Sampling failure sets
  `/tmp/plan056-task4-continuation-stop`; an in-flight page is not canceled.
- [Completion filter](../../scripts/diagnostics/plan056_continuation_completion.sh):
  one 10-second read of at most 10,000 log lines from the last 12 minutes;
  emits only exact-prefix request indices 1–12/statuses, or missing result.

The continuation copies the previously reviewed collectors with only route,
count, temporary-path and duration reductions. Original main-pass artifacts
remain intact; historical hashes continue to describe their executed versions.
Stop on any collector failure; no retry, alternate login/role or fallback.

## Run after approval

1. Through the shared helper create a fresh directory with the prefix above.
   SCP only the five listed files to the same private target; verify local and
   remote SHA-256 before execution. Confirm three container Python destinations
   `/tmp/plan056_http_continuation.py`, `/tmp/plan056_http_pilot.py`,
   `/tmp/plan056_db_observe.py` and the continuation stop flag are absent.
   Abort rather than overwrite. Copy the three Python files and verify hashes.
2. Via the helper invoke by path:

   ```sh
   timeout 600 sh /tmp/<exact-created-directory>/plan056_continuation_host.sh
   ```

   Capture already-redacted output locally to avoid truncation; return compact
   aggregate findings, not credentials, HTML or raw logs. Overall setup,
   measurement and completion observation budget is 12 minutes; no retries.
3. Run the completion filter once with the emitted 32-hex prefix. If a timed-out
   request lacks completion, allow at most 70 seconds, then one final bounded
   filter read. Make no further measured page GETs or cancellation. Missing
   logs leave server completion unknown; client timeout is not a server deadline.
4. Verify collector/database closure, sampler exit, wrapper result and normal
   logout. A wrapper timeout does not prove remote execution ended; report
   uncertainty and retain cleanup pending where necessary. Do not claim session
   cleanup unless logout confirmation was emitted.
5. Hash-check/remove only the three copied container Python files, any known
   continuation stop flag, five host files and observer.done; rmdir the empty
   host directory and confirm absence. Container root is permitted only for
   root-owned diagnostic cleanup, never SQL. No wildcard/recursive deletion.
   Remove the local redacted capture after preserving aggregate evidence.

## Interpretation and validation

Report attempted pairs, incomplete attempts, exact log completion, concurrent
resource/global-counter observations and job samples. Do not attribute global
counters entirely to a request or equate buffer reads with physical I/O. First/
repeat worker/cache state is unknown; this later window is not comparable load
by default. No ordinary-user, cold-cache, percentile, capacity or Home acceptance
claim. Historical Coverage outcome remains unknown. Task 4 completion requires
review of measurements and remaining gaps, not merely a successful wrapper.

Python AST/import, exact route/stop-path checks, Ruff/format, both shell syntax
checks and synthetic completion-log checks pass. The synthetic fixture confirms
only this prefix's indices 1 and 12 appear, excluding index 13, another prefix
and unrelated/private placeholder text. Registry and whitespace checks pass.
No test files, application edits or external access during preparation.
Full continuation/SQL/live compatibility remains unverified; original auth and
SQL behavior were demonstrated by the prior pass, not by this local check.

Reviewed SHA-256 prefixes: HTTP `9286654af4d3`, auth `f25246f3e3b1`, SQL helper
`8852e6534500`, host `b17f17aacf53`, completion `fe3535a6e146`. Compare full
local/remote hashes before execution.

## Execution outcome

All 12 GETs returned 200 and matched exact access-log completion markers. All
24 SQL snapshots succeeded; sampler/collector ended with wrapper exit 0 and
normal logout confirmed. Hash-verified temporary files and the empty directory
were removed; absence confirmed. No retries, Coverage replay or business changes.
Results and limits: [evidence record](PLAN-056-platform-performance-assessment.md#task-4--approved-six-page-pass-completed-2026-11-10).
Task 4 remains open on the unresolved Coverage stall. Next prepare its bounded
component diagnosis; this completed pass authorizes no additional observation.
