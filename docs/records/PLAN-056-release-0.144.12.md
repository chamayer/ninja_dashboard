# PLAN-056 — Production candidate 0.144.12

## Scope and authorization

User chose production after the candidate-environment question. This authorizes
preparing the Software-only release for review; commit and push still require
separate approvals under AGENTS.md. No manual deployment/migration is proposed.
Candidate base is ae45b463 / 0.144.11 on master.

The candidate includes the Software owner/reader components, finite W1–W4
signals, atomic preparation/publication, protected-state rendering and accurate
title-status copy. Existing unrelated Home changes, migration 0406 edits,
test changes, scratch probes and set-aside speculative drafts are excluded.
The candidate's current acceptance snapshot retains current proof/limits;
the original larger acceptance history remains preserved in the main workspace.

## Production effect of an approved push

Push origin first, then the required mirror. Origin/master is watched by
Portainer and automatically builds/deploys. Do not request a separate redeploy.
Operations startup applies pending Django migrations:

| Migration | Reviewed effect |
| --- | --- |
| 0407 | Empty software_overview_current table, RLS/revokes, protected initial view and Software-owned calculation function; explicit required owner reads. No initial data build. |
| 0408 | Expiry predicate callable by the existing scheduler role. No new schedule. |
| 0409 | Owner-checkpoint index on operator_job_runs, existing Jobs input/claim fencing, preparation/publish wrappers and retry admission. Runtime unfenced calculation revoked. |
| 0410 | Protected reader function and revocation of the earlier view bypass. No route activation or certification. |

0406 is already deployed. Read-only production metadata confirms ingest SQL
migrations through 119 are applied; the candidate adds no ingest SQL migration.
The deployed migration owner is superuser, so 0407's cross-owner GRANTs can be
applied. This is observed privilege metadata, not endorsement of broader access.

0409 creates its index nonconcurrently during migration: it scans retained Jobs
runs and can briefly block writes. Duration is not measured. No workstation
performance run or production schema change was performed. Migration code has
reverse SQL, but rollback is a separately authorized action and is not automatic.
0407 reverse retains previously granted owner reads rather than guessing which
grants preexisted. Older runtime must be restored before reversing its APIs.

Existing Jobs will register the new definition/successor snapshots at service
startup. Normal relevant writer/owner signals can request prepared publications.
Readiness, assessments, exposure and aggregate run within the existing Software
resource/tenant findings guard; production throughput/contention remain unproved.
Initial forced publication is not part of push approval unless explicitly included.

## Visible behavior and activation boundary

The default page retains live reads; prepared outputs remain contract_ready=false.
Products/search/CSV stay on existing semantics. Copy now says No open decision
issue rather than implying safety approval. No latency/freshness improvement or
contract certification is claimed. Producer resets certification, so changing
one aggregate row would not constitute sustained activation.

The existing shared superuser ingest limitation is recorded; no role/credential
migration or expanded grants are included. The user rejected adding role
redesign. That direction does not prove or waive the security contract.

## Validation

Completed in a detached worktree based on ae45b463 with only this candidate:
- Django system check; template loading; migration graph ending at 0410; shared
  Jobs registry validation; plan-registry validation (55 entries).
- All 19 existing Software review checks and three existing assessment/exposure
  checks passed. No tests were created, edited or copied from the changed local
  test files.
- Changed modules/migrations compile; eight ingest/helper files pass Ruff.
  Existing admin/view/finding-registry warnings remain at HEAD counts (1/96/3).
  No new enclosing-function/lint-code locations were introduced; existing
  complexity warning counts changed where existing functions gained hooks.
- Current candidate document links, blueprint limits and whitespace checked.
  Home cache/read-model changes and migration/test 0406 changes are absent.
- Reviewed Docker directory copies include every new runtime file. No image,
  dependency, Compose, entrypoint, port or schedule change is required.

The six previously recorded Jobs expectation failures are unresolved and were
not rerun or edited. Five predate this work; exact catalog/workflow assumptions
need authorized test updates. These 22 passing focused checks do not imply a
passing broad suite or complete contract acceptance. Earlier synthetic Jobs/
failure/permission checks retain their owner-role/disabled-intelligence limits.
No local fleet, benchmark, service migration or production write was performed.
Read-only production metadata checks only were used during release preparation.

The exact 37-file candidate is staged for commit review; patch/manifest are
retained locally in .git. The temporary validation worktree was removed. Original working changes stay
preserved, including the full acceptance history. Candidate acceptance.md is a
concise current snapshot, so older local history remains outside this commit.

## Next action

Finish candidate checks and save its exact patch. Obtain commit approval for
this single logical Software preparation release. After commit, separately
request push approval explicitly covering automatic deployment and 0407–0410.
Then perform only the separately approved production publication/acceptance
steps; certification and live route cutover remain open.

## Commit checkpoint

User separately approved commit. Created a289e80a, Prepare Software overview
publication as 0.144.12. All 37 committed blobs match the reviewed saved manifest;
the index is empty and unrelated working changes remain uncommitted. The commit
governance hook passed with one existing current-state status-date warning.
Origin/master remains ae45b463 at the read-only pre-push check.
Push approval is still required and must explicitly include automatic deployment
and 0407–0410. No push, migration, producer or deployment was performed.

## Approved push checkpoint

User separately approved push, explicitly including automatic production
deployment and migrations 0407–0410. Pushed a289e80a to origin/master first,
then a-m-rose/master. Both remote tips independently verified at
a289e80a89caac0b2df06635acb8b76612678cdd. Initial read-only service metadata
still showed the previous healthy containers; rollout verification is pending.
No manual redeploy, migration command or initial publication Job was invoked.

## Deployment verification failure

Automatic rollout applied 0407–0410. Operations and ingest replacement
containers are running/healthy. The Jobs worker restarts before readiness:
register_recovery_policies calls jobs_register_recovery_policy_v1 for
software-catalog, which rejects missing matching database authority.
Read-only metadata confirms both new Jobs have snapshots but neither has a
job_recovery_policy_authorities row. Fixed startup messages identify the same
failure. The earlier synthetic flow did not exercise this startup boundary;
its structural fixture preparation masked the missing migration requirement.

Deployment is not successful. Prepare a minimal 0411 two-authority seed
correction, validate real registration, and obtain new commit/push approval
explicitly covering that migration. Do not weaken or skip the registration
guard. No manual migration, redeploy, forced Job or rollback was invoked.

## Approved immediate correction and durable 0411

After the missing-authority failure was explained, user approved the correction
and directed immediate action. Applied only the two authority UPSERTs from the
reviewed 0411 SQL using the approved helper and direct psql in a bounded
transaction; INSERT 0 2 and COMMIT succeeded. No migration ledger row was inserted,
no guard bypassed and no redeploy/forced Job was triggered. Worker recovery uses
its existing restart policy. 0411 remains pending for normal Django application.

Before production application, a tiny synthetic PostgreSQL fixture used the
actual jobs_register_recovery_policy_v1 function: missing authority rejected;
0411 enabled both exact current definition/evidence registrations; repeating
migration/registration was idempotent and an unrelated authority was unchanged.
The temporary fixture was removed. No test files changed.

0.144.13 / 0411 is the durable source correction. It needs its own commit and
push approvals; push would automatically deploy and apply idempotent 0411.
Existing 0.144.12 live-reader/uncertified-publication boundaries remain.

## Remaining scheduler lock and minimal correction

After the approved authority correction, both startup policies registered and
worker restarts stopped at count 14. Readiness remains unhealthy: jobs_request
waits on an advisory lock held by an ingest connection idle in transaction
after RELEASE SAVEPOINT. Source confirms produce_due_schedules called the new
expiry helper before closing its outer transaction. Scheduled admission held
locks while the helper opened another connection and waited on them.

0.144.13 moves only the expiry helper call after outer connection closure.
A focused check executed the actual scheduler function and verified connection
closure/leader release before expiry admission, preserving admission counts.
Ruff passes. No test files changed; no lock holder terminated or manual restart.
The corrected code must deploy before readiness can be claimed.

Runtime hashes for Operations reader/0410, ingest publisher/shared registry and
worker dispatcher/shared registry match a289e80a. Ingest/worker VERSION is
0.144.12; the 0.144.13 correction is prepared, not deployed.

## Approved 0.144.13 commit and push

User answered yes to the separately queued commit and push approvals, the
latter explicitly including automatic deployment and idempotent 0411.
Committed ff63104a, Restore Software Jobs startup and expiry admission;
pushed origin first, then a-m-rose. Both remote master tips verified as
ff63104a042dd46dd466a264692ec6ba67e740a3. The exact corrective commit has
eight scoped files; unrelated work remains uncommitted. Governance passed with
the existing stale current-state status-date warning.

Portainer's automatic rollout has begun. Final health, current runtime files
and applied 0411 are being verified. No separate redeploy or forced Job.

## Verified corrected deployment — 2026-11-12

Automatic rollout of ff63104a / 0.144.13 completed. Postgres, Operations, ingest
and Jobs worker are running/healthy. Replacement application containers report
zero restarts. Both producer containers report VERSION 0.144.13. SHA-256 values
for operator_job_queue.py in ingest/worker, Operations views.py and migration
0411 match the committed blobs. Both remote master tips were verified at
ff63104a042dd46dd466a264692ec6ba67e740a3.

Read-only database verification confirms 0407–0411 applied and both Software
recovery authorities/policies present. Worker startup readiness now passes,
confirming the prior registration/transaction startup blockers are cleared.
No manual redeploy, lock-holder termination, guard bypass or forced initial
publication was performed. The earlier specifically approved authority
insertion is recorded above; 0411 now makes it durable.

Deployment stage complete, contract acceptance open: default Software retains
live reads and prepared publication remains uncertified. Production publication,
compatibility, freshness/full-HTTP acceptance and sustained activation remain
separate work. Existing superuser access and prior coverage limits are not waived.
Unrelated working changes remain uncommitted; no follow-up commit was made solely
to record this commit's hash.

## End-to-end Software activation — in progress

User explicitly directed fixing the slow page end to end in production without
added scope. Governed overview 3ba0107f-0c66-44db-9220-ec46f3ee0ce7 failed safely
under the broad collector-status gate. The queue failure is the existing
retained-inventory per-computer refresh error, not failed local publication.
Current checkpoints must distinguish attempted collection from published inputs.

Minimum correction: publication-owner checkpoints, existing reclassification/
ownership dirty signals and completion-only overview admission through existing
conditional workflows. Future dependency-only queues do not imply committed
operator changes; actor requests remain invalidating. v4 avoids the old future
dependency backlog. No new collector, service, table, role, receipt or cadence.

A production REPEATABLE READ snapshot compared private aggregate calculation
against the compatibility reader running as operations_app: all 15 context
fields matched, including nested risk/workflow/week data. Values were discarded;
aggregate write rolled back. Reviewed script:
scripts/diagnostics/plan056_software_parity.py.
0412 bodies and all Job snapshots passed actual DB validation in a transaction
then rolled back. No activation SQL applied.

Local 0412 promotes reviewed fenced generations, and HTML selects the prepared
reader. Checks, exact candidate assembly, approvals, deployment and completed
publication/HTTP acceptance remain. Clean the two remote temporary scripts
after verification. No role redesign or unrelated troubleshooting is added.

## 0.144.14 activation candidate

User directed no extra testing and finishing the page fix. Existing production
snapshot parity and rollback-only SQL/definition registration checks passed.
The bounded candidate selects the protected HTML reader, updates existing
functions through 0412, and admits overview on the existing completion signal.
No collector behavior, table, grant, role, service or cadence change.

Pending push approval must include automatic deployment and 0412. Existing
function owners/grants are retained by CREATE OR REPLACE; reverse restores
previous bodies and clears certification. Unrelated Home/test work is excluded.
Remaining work is real governed publication and full-page verification, not
another local test campaign.

## Approved activation push

User separately approved the 0.144.14 commit and push/activation deployment
including 0412. Created cb86836b, Activate the published Software overview;
pushed origin first, then a-m-rose. Both master tips verified as
cb86836b5ed5fc0dd509e5e9b8c6e87fe59f557a. Exact 11-file candidate matched
the saved manifest; the only staged views change is the reader switch.
All unrelated Home/test working changes remain outside the release.
Automatic rollout is in progress; no manual redeploy or extra tests.

## Whole-platform investigation checkpoint — 2026-11-12

Subsequent external checks confirmed cb86836b / 0.144.14 and 0407–0412
deployed with healthy services. Software remains empty: no publication exists.
Do not treat deployment health as functional acceptance.

The user redirected recovery to the whole platform and the top slow-page
entries, then challenged incremental patches before identifying the root cause.
Local Sources-count migration 0413 and compact global Issues count candidates
are paused, uncommitted and unapplied. No further release is prepared.

In one runtime-role, read-only repeatable-read snapshot, Sources counts took
4.874 s versus 0.248 s when grouping streams before companion-policy lookup,
with identical results. Global Issues count took 1.057 s versus 0.725 s using
the existing compact selector, also equal. These prove bounded improvements,
not a cause shared by every slow page. A separate real Home HTTP request took
11.615 s, returned 200, and logged out normally.

A bounded runtime-role EXPLAIN ANALYZE pass of existing SELECTs, in a read-only
repeatable-read transaction with 20-second statement/1-second lock deadlines:

| Existing read | Execution | JIT compilation |
| --- | ---: | ---: |
| Sources record counts | 4.166 s | 0.053 s |
| Source Records default 100-row page query | 7.883 s | 0.359 s |
| Inventory Clients source-coverage query | 0.453 s | absent |

The largest reported nodes showed zero temporary blocks. Sources' observation
scan included most execution time; its predicates contain per-record companion
policy evaluation. Source Records' largest nodes include nested joins and the
query still materializes a tenant-wide group-mapping relation after selecting
the page. Node timings are inclusive and must not be summed. Inventory Clients'
other readers and Source Records' detailed internal cost shares remain gaps.
Shared observation data alone therefore does not establish a common bottleneck.
This is not an entire-page timing comparison or proof all spills are absent.

Host samples showed available CPU/memory, low I/O wait and low swap traffic;
DB samples showed no blocking edges. These observations do not exclude every
intermittent contention event. No server tuning, cancellation, restart, data
rebuild, migration, application deployment or test-file edit occurred in this
investigation. Diagnostic emitted only plan metadata/timings, no rows or SQL.
Script: scripts/diagnostics/plan056_top_read_plans.py, SHA-256
5a0692641cbc7abfef25ab46c316ae4804c81503d3220d870447749e6ad2493e.
Connection closure confirmed; no retry. The platform-wide root cause remains
unproven; do not present individual query corrections as platform acceptance.

## Retained early component comparisons

Before the Source Records final candidate, runtime-role read tracing measured
Source Records 6.245/6.362 s SQL/wall and Inventory Clients 4.481/5.056 s.
Limited same-snapshot query comparisons returned identical results: Sources
stream counts 4.874 -> 0.248 s, Source Records bounded detail/batch attribution
5.590 -> 1.124 s, Inventory Clients compact evidence 2.372 -> 0.273 s.
A simple page-ID join alone did not improve performance and was rejected.
These are earlier component observations, not full HTTP acceptance or a universal
diagnosis. Later Source Records checks supersede them for its active candidate;
other local candidates remain excluded from that release.
