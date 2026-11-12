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
