# PLAN-056 — Bounded measurement protocol

## Current cold-navigation measurement disposition

User deferred outstanding item 4 to post-fix verification. No additional server
or cold HTTP request was started; the fresh-worker proposal is withdrawn from
current execution. Continue the platform assessment. Cold-response acceptance
remains required after a fix; it is not a prerequisite to finishing diagnosis.

## Current Coverage measurement disposition

User deferred outstanding item 2: additional unchanged Coverage timings are
irrelevant to the current assessment because the bottleneck is confirmed.
The proposed two-request 75-minute-per-request extension is withdrawn; no
approval is pending and no long request was launched. Retain existing failure,
actual-plan and candidate/reference evidence. Successful full-page/first-repeat
timings remain post-fix validation after an approved fix. Continue the other
measurement items; do not replay known-expensive Coverage to obtain another
pre-fix baseline. No implementation/deployment authorization is implied.

## Current ordinary-user measurement disposition

For item 3 the user confirmed no non-admin Operations account exists. Ordinary-
user timing is not applicable to the current deployment; retain admin results
as admin-only and revisit if a non-admin account is introduced. Do not create
an account, change roles, impersonate a user or insert a synthetic session to
fill this matrix. No ordinary-user authentication or page request was performed.

## Resumed active-work correlation

The resumed platform-wide assessment retains the user's full read-only bulk
measurement authorization recorded in the current handoff. Use the existing
reviewed `plan056_current_jobs.py`, `plan056_db_observe.py` and
`plan056_host_observe.sh`; do not change roles or enable instrumentation.

One current-Jobs invocation is the gate. If no scheduled run is running, stop
without another idle window or polling. Otherwise run the existing five-sample,
60-second host/database protocol once, then one current-Jobs snapshot to bound
the overlap. Record table/database deltas only across unchanged reset epochs;
job overlap is correlation, not per-job attribution. Existing-role hidden
locks/session timing remain unknown. No manual run, HTTP replay or cancellation.

Transfer only these three files into a fresh `/tmp/plan056-resume.XXXXXX`
directory. Use the shared helper for remote commands and the same private SSH
target for SCP. Verify all SHA-256 hashes, refuse existing container paths, and
copy the two Python files by path to `/tmp` in `ninja-operations`. The existing
host wrapper retains its 180-second limit and database wrapper its 120-second
limit; each current-Jobs invocation has a 20-second wrapper. Server statement,
lock and idle deadlines remain 3/1/5 seconds. Stop on error, without fallback.
Hash-check and remove only the exact completed diagnostic copies; rmdir the
empty directory and verify absence. No recursive or wildcard cleanup.

User subsequently directed continuing page-load measurement rather than stopping
at an attribution gap. The active-work gate found scheduled work; its one-minute
window ran. Continue with the HTTP pass below, not patch selection.

## Resumed full-page measurement

Under the user's full measurement and explicit page-load direction, repeat the
configured-admin HTTP matrix with the existing normal login/logout, session
housekeeping and redacted passive snapshots. Use no new account or impersonation.
Thirteen route variants, first and immediate repeat (26 GETs maximum): Settings,
Home, Clients, Computers, Issues, Sources, Source Records, Software, Patching,
Jobs with refresh off, Computers page 2, Source Records page 2, then Coverage.
Both page parameters are handled by existing pagination code. No actions or CSV.

Coverage is last so its prior timeout cannot prevent other page observations.
Allow up to 120 seconds per Coverage request to obtain an actual completed time;
other pages retain 20-second deadlines. Stop on the first failure; do not enqueue
another request behind work of unknown completion. No retries or cancellation.
These are internal-loopback HTTP header/full-HTML times, excluding browser assets,
JavaScript, rendering and external networking. First/repeat do not prove cold/hit.

Use the existing matrix/host/completion collectors and authentication/SQL helpers
in a fresh `/tmp/plan056-task4matrix.XXXXXX` directory, hash-verified before copy
and execution. No existing container path may be overwritten. Existing wrappers,
sampling intervals, server-side SQL limits, redaction and completion review apply.
The completion filter accepts this pass's 26 possible markers. Capture all
redacted output locally before summarizing so tool truncation cannot lose data.
Hash-check exact copies before cleanup and verify absence. No runtime edits,
configuration changes, deployments, fixes or performance runs on the workstation.

Task 2 deliverable, 2026-11-09. This defines observations, not authorization to
execute them. PLAN-056 remains the execution authority. Record results in the
[evidence record](PLAN-056-platform-performance-assessment.md).

Task 4 refinement: the [execution review](PLAN-056-task4-execution.md) supersedes
the draft role/request matrix below. Mounted admin credentials provide a normal
login path, pending authorization of session/last-login effects. First establish
access and log completion with one Settings pilot; the later matrix is 11 admin
route variants, excluding the legacy Job status redirect. Ordinary-user results
remain unavailable. The pilot was subsequently approved/executed; the main pass
still needs its reviewed artifacts and external authorization.

## Sequence and limits

1. Task 3: verify running state and collect one 60-second passive resource
   window, at 0/15/30/45/60 seconds. Allow at most 10 minutes total including
   setup and bounded metadata queries; stop on expiry and report missing data.
2. Task 4: after reviewing task 3, observe sequential authenticated page GETs
   with passive resource correlation. One initial and one immediate repeat per
   eligible route/role, at most 40 requests and 15 minutes total. Stop when
   either budget is reached. Do not automate full navigation, subresource loads,
   or polling. A browser interaction follow-up has its own bounded scope.
3. Tasks 5/6: use those observations to select specific read/write paths. Any
   execution plans or further observations get a named query, purpose, timeout
   and count first. No blanket EXPLAIN ANALYZE, full-table count or benchmark.

Run at most one diagnostic SQL connection and one page request concurrently.
The five resource samples may run alongside that request; do not duplicate
collectors. No forced source collection, evaluator, matcher, refresh, retries,
queue changes, maintenance, statistics resets, cache flushing or load generation.
Observe scheduled/manual work already present; label an absent workload rather
than starting it. A second window needs a stated evidence gap and authorization.

## Execution and permissions

Use Windows PowerShell 5.1 with `..\Scripts\Invoke-DevTool.ps1` and the verified
machine-local profile. Inspect profile capability/target without printing its
secrets. Authorization must identify production versus rehearsal and cover the
specific task below. An available profile is not approval. Prepare/review the
exact allowlisted commands or scripts before external execution; redact output
at collection. Use packaged modules, direct SQL to psql, or reviewed `.py` files
copied to a temporary target path and invoked by path; no remote inline Python.
Copying/removing temporary diagnostics must be explicitly within the scope.
Do not install packages or change persistent instrumentation to fill a gap.

Production SQL diagnostics use read-only transactions, application name
`plan056_observe`, 3-second statement timeout, 1-second lock timeout and
5-second idle-in-transaction timeout. Set the tenant context when reading
tenant data. Maximum 12 one-off metadata statements plus one bundled statistics
statement per resource sample. Bound arrays/rows before client output; no
customer identifiers, SQL literals, query text or payload columns. Use the
least existing role that permits required monitoring; if permission is missing,
report the gap without granting privileges or bypassing RLS. System views may
require monitoring privileges; runtime-role visibility is not fleet visibility.

Timeouts are failed/incomplete observations, never completed timings. Do not
retry a timed-out diagnostic during the same window. Stop if the diagnostic
blocks, resource sampling fails twice, user reports worsening service, or a
page fails/times out. Collect one bounded final activity sample, then end the
window. Preserve uncertainty; no sustained observation or repeated trials to
force a favorable result.

## Task 3 — Running state and resources

Collect only allowlisted fields; never dump `docker inspect`, environment,
process command lines, raw logs, settings or connection strings.

| Question | Evidence and method |
| --- | --- |
| What code is running? | Container image IDs, optional revision labels, start/health state; hashes of selected runtime files against local committed and worktree content. Include matcher, shared registry, Home/Issues/Software/Patching readers, middleware and startup files. An image name or VERSION alone cannot prove deployed commit. |
| Which migrations exist? | Latest/targeted applied migration names from Django and ingest ledgers, including 0405/0406 and 119; catalog presence/signatures of the attribution function, patch summary/trigger and active-findings index. Review the ingest ledger schema locally before querying. No migration commands. |
| What is configured? | Whitelisted Postgres version and memory/connection/planner settings; active Gunicorn worker/thread/timeout values and container CPU/memory limits. Default values remain distinct from observed values. Inspect config fields without printing secrets. |
| Is the host constrained? | CPU use and runnable tasks, available memory, swap-in/out deltas, disk throughput/latency/queue where available, filesystem free space; per-container CPU/memory/I/O deltas and limits. Include shared non-Ninja services using anonymous workload labels. Missing tools mean missing metrics, not installation. |
| Is Postgres constrained? | Connections by state/application, active and idle-transaction age buckets, waits and blocker counts/ages, database buffer/temp/deadlock/I/O counters and reset timestamps. Report deltas over the same 60 seconds and relation-level estimates for known hot tables. No raw SQL text or customer data. |
| What is running? | Bounded Jobs diagnostics for active runs, waiting age, dependency reasons, execution/resource claims, scheduler/worker heartbeat age and enabled schedule cadences. Limit each diagnostic section to 50 rows; aggregate totals if already cheap. Replace run/binding IDs with local aliases. Source bindings expose cadence/enablement only. |
| What creates database churn? | `pg_stat_user_tables` write/dead-row estimates and vacuum/analyze counters for observations, software installations/readiness, relationship evidence, requirements, findings/assessments, CVE matches and activities. Capture both endpoints; state resets and estimated counts. Table/index/TOAST sizes are bounded catalog metadata, not content scans. |

Use existing pg_stat_statements only if installed, enabled and accessible.
Return at most 10 query IDs and aggregate timings/calls/rows/temp/shared-block
metrics, excluding query text. Historical cumulative averages and maxima do not
describe this window; take deltas where possible. Do not enable extensions,
logging, track_io_timing or tracing. If CPU/I/O or query attribution is unavailable,
retain the gap for a separately reviewed instrumentation proposal.

## Task 4 — Request matrix

Use normal GET, default ordering and first page, no search/client filter unless
listed. No CSV/export, detail payload harvesting or action endpoints. Audit the
selected GET code for enqueue/refresh side effects before first invocation;
omit unsafe routes pending review. Ordinary access means an existing user
authorized for that view; staff-only pages use an existing staff session.
No permission elevation, new users, impersonation or synthetic sessions.

| Page | Route | Role and variant |
| --- | --- | --- |
| Home | `/` | Ordinary and staff; captures differing card composition |
| Clients | `/orgs/all/` | Ordinary, authorized portfolio |
| Computers | `/devices/` | Ordinary, default first page |
| Coverage Computers | `/inventory/computers/` | Ordinary, default; `/coverage/` is the same handler, not a second sample |
| Issues | `/findings/` | Ordinary, default queue |
| Sources | `/sources/` | Authorized role, default overview |
| Source Records | `/inventory/source-records/` | Ordinary, default first page |
| Software | `/software/` | Ordinary, default overview |
| Patching | `/patching/` | Ordinary, default queue |
| Settings | `/admin/settings/` | Staff |
| Jobs | `/admin/jobs/` | Staff |
| Job status | `/admin/jobs/status/` | Staff, one GET; no polling |

This is 13 route/role pairs, at most 26 initial/repeat requests. Remaining budget
allows at most four paired variants selected after initial results: one
non-identifying supported filter, page 2, or shared-navigation comparison.
Record exact sanitized parameters and why selected. Do not broaden scope to fill
the budget. If no authorized ordinary session is available, leave those rows
unmeasured rather than substituting staff.

Use the existing secure session/profile without displaying credentials, cookies,
responses or customer content. The old `.plan044_home_probe.py` creates/deletes
session rows and chooses a user; it is excluded from read-only scope. Acquiring
new authentication or any session mutation requires a separately explicit scope.
Normal application session/access-log effects of authorized GETs must be stated;
read-only here prohibits business/configuration mutations, not those effects.

Record UTC start/end, route/role alias, target endpoint, status/redirect, time to
first byte and complete body, body byte count, timeout/disconnect, resource window
and active job aliases. Discard body content. A login redirect is not a page
success. Fix the same internal or external endpoint for comparisons; label
proxy/network inclusion. Do not use Django test-client timings as HTTP latency.

Use a 20-second client deadline and record any existing server deadline. Client
timeout does not stop server SQL. Before starting, establish an attribution and
completion check using existing request/access-log correlation, worker/backend
identity or observer activity. Never infer exact attribution from overlapping
timestamps alone. After a timeout, issue no further page requests: observe for
at most the configured server deadline plus five seconds, capped at 70 seconds.
Stop if attribution/completion cannot be established. Cancellation is excluded
unless explicitly authorized for the exact diagnostic backend; never cancel a
background/user query merely because it is slow. No job cancellation.

Label first-observed and repeat requests accurately: first observed is not a
proven cold cache; repeat may hit a different Gunicorn worker. Record process
identity/cache telemetry only if already available. Do not flush/restart/pin
workers or infer cache-hit status solely from speed. This protocol cannot prove
cold-request acceptance, load capacity or tail percentiles from one pair.

## Background observations and later attribution

Observe source collection → ownership/resolver → assessment/evaluation and
software queues → readiness/classification/matcher as the deployed dependency
catalog establishes them. Also track retention, rollups, notifications and health
work present in the window. Read at most 20 recent terminal run summaries per
selected job family within 24 hours, using reviewed indexed predicates and
timeouts; if slow, omit rather than scan history. Capture duration, outcome,
scope size/changed rows when already recorded, waits and predecessor/successor
aliases. Do not claim comparable duration across different scope or data volume.

Task 5 compares expensive reads with selected-row counts, limit placement,
shared consumers and existing plans. Task 6 relates write-counter deltas and
waits to actual writers; correlation alone does not establish causation. Raw
counter volume does not distinguish material changes from timestamp-only writes.
Any expensive plan execution, full-run timing or concurrency experiment belongs
on an authorized representative rehearsal environment, with production side
effects disabled and a separate protocol. No such environment is assumed here.

## Deliverable and interpretation

Store compact per-window/request tables, code identities, metric deltas, known
workload, protocol deviations and gaps in the evidence record. Distinguish
confirmed observation, supported hypothesis and unavailable data. Do not add
separate component timings to fabricate an HTTP breakdown. Avoid declaring
memory, SQL or locking the root cause from a single sample.

Task 3 is ready to prepare exact diagnostic artifacts and seek authorization;
its gate covers deployed-state/metadata and the single passive window only.
Task 4 requests and deeper attribution receive their own reviewed scope after
task 3. Pending contradiction: docs/operations.md prescribes a separate redeploy
after a push, while root AGENTS.md explicitly prohibits it. AGENTS.md controls;
this protocol performs neither operation.
