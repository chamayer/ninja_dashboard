# PLAN-056 — Step 3 resource-correlation execution review

## Status, question and authority

Prepared locally 2026-11-10 after the user requested finishing big-picture step 3.
**Approved attempt stopped at the natural-work gate; further investigation deferred.**
No sampling ran. The earlier resource synthesis and recovery ranking do not
establish resource interaction. No fix or new test is requested.

Current direction: user deferred this investigation until larger demonstrated
defects are fixed. Root TODO.md owns resume conditions. Do not seek another
attempt now; resource-interaction evidence is not a prerequisite to step 4.

Question: during naturally active reviewed work, are visible database backends
computing, waiting on locks/I/O, or accompanied by host memory/disk pressure?
Which statement families own that activity, and do naturally present page readers
show blocker edges to background sessions? Existing global counters/runtime-role
visibility cannot answer this. Do not collect another idle baseline.

External execution needs explicit approval under AGENTS.md and PLAN-056's
registry gate. Approval of this protocol would cover read-only catalog/Job
metadata, numeric host/process counters and temporary-file transfer/cleanup only.
It does not authorize implementation, instrumentation, grants, business-data
reads, HTTP/authentication, Jobs execution, cancellation, configuration, migrations,
commits, deployment or maintenance. The existing `ninja` local inspection identity
may be privileged; its previous Coverage-only authorization is not reused.

## Reviewed artifacts and bounds

- [Shell collector](../../scripts/diagnostics/plan056_interaction_observe.sh).
- [Visibility/natural-work gate](../../scripts/diagnostics/plan056_interaction_gate.sql).
- [Per-sample SQL](../../scripts/diagnostics/plan056_interaction_sample.sql).

Use the existing Postgres container on the same assessment host through the
shared `../Scripts/Invoke-DevTool.ps1` SSH helper. No remote Python execution.
One short preflight connection (10-second process cap), then one sampling
connection (80-second cap); never two observer connections simultaneously.
Default read-only, 3-second statement, 1-second lock and 5-second idle-transaction
limits. Each sample autocommits; do not hold a minute-long transaction.
Outer collector deadline 105 seconds. No automatic retry or scope fallback.

Preflight must confirm expected database, read-only mode, full statistics
visibility and at least one naturally running allowlisted Job. Otherwise stop.
Job keys were checked against `shared/jobs_registry.py`; progress fields against
migrations 0179/0209. No deployment-definition assertion is made: missing schema
or permissions fail closed. Do not poll for a convenient Job or force one.

Thirteen paired samples on a five-second schedule span approximately 60 seconds.
Each captures at most 50 active/idle-transaction database sessions and 50 current
running/queued Job rows; retain counts/truncation. Report backend PID/start/leader,
query/transaction age, wait category/event and blocker PIDs. Raw SQL is used only
inside the server to choose reviewed family aliases; never emit SQL, bind values,
users, client addresses, source identifiers, payloads or connection strings.
Family matching is a coarse lead, not exact function/phase attribution; unknown
statements stay unclassified. Job/run and stage aliases retain transitions without
printing raw IDs or arbitrary stage/detail text. Job metadata is tenant 1 only.

Host samples collect aggregate CPU, memory/paging/pressure counters, data-device
disk counters and at most 50 Postgres process CPU/RSS/I/O counters. Read process
IDs through `docker top ... -eo pid`; never command arguments. Namespace PIDs
join process counters to database PIDs; backend start/process start distinguish
reuse. Missing/disappearing process/I/O fields are explicit limitations. Host
clock tick/page size are collected to interpret deltas. Other databases' process
totals cannot be assigned to Ninja queries without matching session identity.

Resolve only the documented `/var/lib/postgresql/data` Docker mount and use
`findmnt` to emit its major/minor device number. Do not emit volume/source paths.
Stop if mapping fails. Device totals are shared-device activity, not exclusive
database ownership; unavailable device counters preclude a device-latency claim.
Host and SQL timestamps are distinct endpoints; retain their offsets.
Database aggregate counters remain contextual, not a per-Job write ledger.

## Transfer, invocation and cleanup

After approval, record local SHA-256 for all three exact files. Create one fresh
`/tmp/plan056-interaction.XXXXXX` directory with `mktemp -d` through the shared
helper; transfer only these artifacts to absent filenames using the existing
private SSH profile. Verify hashes before invoking the script by its exact path
with `timeout 105 sh`. Do not use guessed credentials, raw environment/inspect
output, recursive deletion or a reused diagnostic directory.

The wrapper creates only `host.capture` and, on producer failure, `producer.failed`
inside that directory; umask 077. The capture contains numeric redacted metadata.
Preserve command completion/exit status and redacted output outside Git.
Hash-check the three transferred source files again, remove those exact files
and the two named generated files if present, then remove the empty directory
with `rmdir`. Confirm absence. No files copied into the database container.
Interrupted sessions/processes expire through the fixed timeouts; no backend
cancellation is authorized. If closure is uncertain, report it and prepare a
separate exact-state inspection rather than continuing observation.

## Interpretation and completion criteria

Produce a resource-interaction matrix, with confidence and sampled coverage:

| Dimension | What this pass can establish | What it cannot establish |
| --- | --- | --- |
| Computation | CPU deltas for observed stable backends, aligned statement-family snapshots | Exact CPU per short statement; SQL ownership between samples |
| Locks | Directed blocker edges and observed waiting-query/transaction ages | Absence of intervening waits; causal page impact if no page is observed |
| I/O/spill | Backend physical-byte deltas, I/O waits, mapped disk intervals and global temp changes | A per-statement temp-byte ledger or exclusive shared-device attribution |
| Memory | Host pressure/paging/availability plus backend RSS observations | Additive PostgreSQL memory from RSS, exact work_mem sizing, historical peak pressure |
| Jobs | Stable run/stage transitions and temporal overlap with SQL families | Exact Job-to-backend mapping: source uses generic `ingest` labels, no proven run/backend identifier |

Report observed page-to-background blockers only where backend identities and
statement families support the relation. Overlap is not proof that a Job slowed
a page. No page requests are initiated: if no natural reader appears, page
interaction stays unmeasured and the pass must not close that question. A named,
bounded reader observation or instrumentation proposal would then be the next
decision, not another broad pass or an implementation shortcut.

Step 3 can close only after the matrix distinguishes demonstrated interactions,
reasonable exclusions within sampled windows, and remaining decision-relevant
unknowns with their required next evidence. One successful passive pass is not
guaranteed to achieve this. Do not mark it complete merely because sampling ran.
No controlled interference experiment, full per-Job cost measurement, browser
timing, retention decision or deferred Coverage/cold replay is included.

## Local validation

Shell syntax and metadata/source review; registry, links, whitespace and handoff
size checks. No new tests or runtime changes. Live preflight results below
supersede the earlier unverified visibility/natural-work assumptions; sample SQL,
host mount/process permissions and counters remain unvalidated.

## Approved attempt — 2026-11-10

User explicitly approved this protocol. Transferred the three reviewed files to
fresh directory `/tmp/plan056-interaction.QC8z3U` through the existing SSH profile;
all hashes matched before invocation and again before cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `plan056_interaction_gate.sql` | `a5b2eeba24e9fdb5d0973e8e86c042b8e641f42ad9cf3598624d10e0e28f7277` |
| `plan056_interaction_sample.sql` | `92aef0f5de094cc6ab72d95189b6cc74d1f5cb298d831e61203d2c7824b21d45` |
| `plan056_interaction_observe.sh` | `86c7321e56fb9f3bf35625d627dfaacb534f1e9e899035f3fa3d03c946ff5fc9` |

Executed exactly once through Invoke-DevTool.ps1 with the 105-second outer bound.
At `2026-11-10T23:27:41.232446+00:00`, preflight returned expected database,
read-only mode and full statistics visibility, all true. The remaining
natural-work EXISTS gate then raised its deliberate division-by-zero stop;
wrapper/psql exited 3. There was no running tenant-1 Job in the reviewed
allowlist at that instant. This does not assert that every Job or database
session was idle. The script reached neither host mapping nor sample execution.

No host capture or producer-failure file existed. The preflight psql process
exited; no sampling process/connection was launched. Exact transferred files
were hash-checked and removed, the empty directory removed with `rmdir`, and
absence confirmed (`interaction_cleanup_verified`, cleanup exit 0).
Redacted execution output is retained outside Git in the local temporary
`plan056-interaction-QC8z3U.capture` file.

No retries, polling, HTTP requests, forced Jobs, cancellation or production
changes. The attempt establishes inspection visibility, not resource interaction.
The single-pass approval is consumed. Further investigation is deferred by
user direction; see root TODO.md before preparing any new observation. Do not
rerun automatically or block remedy comparison on this incomplete investigation.
