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
