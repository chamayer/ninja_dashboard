# Active Operations implementation plan

## Status

Implementation and shadow validation complete; preparing authorized release
0.123.0. Commit/push and the repository-required coupled redeploy are authorized.
No migration or live finding enforcement change is included.

## Goal and scope

Deliver stable legacy correlation references, typed multi-participant contracts,
evaluation coverage, dependency decisions, all 53 type mappings, and an opt-in
read-only shadow comparison. Preserve finding IDs, decisions, notification keys
and current subscriber behavior. Enforcement is separately gated in the runbook.

## Files and decisions

- `apps/core/conditions/`: pure contracts/engine, validated JSON profile,
  PostgreSQL snapshot reader and aggregate report.
- `compare_conditions` management command; no apply mode or scheduler.
- Focused conditions tests, ADR-0020, runbook and enforcement backlog entry.
- Root VERSION/CHANGELOG for approved release preparation.
- No schema/dependency change. Existing Dockerfile includes all runtime files.
- JSON policy is reviewed shadow input, not new production policy authority.
- Missing identity readiness and required collection scopes stay unknown.
- Candidate software fanout is not represented as exact production exposure.
- The legacy plan contained unrelated historical tasks; Git preserves them.

## Validation completed

- 38 focused tests pass; focused Ruff and format checks pass.
- Django system check passes; migration-state check reports no changes.
- Extended checks: 53 passed, one pre-existing Findings-template test failed
  because it expects an optgroup absent from the committed template. Both
  the template and that test are unchanged by this task.
- Local Python is 3.14; injected in-memory shadow code also ran successfully
  in the deployed Python/Django runtime, using a read-only database snapshot.
- Live shadow run completed in about 22 seconds; all 53 registered types are
  mapped, and no invalid identity members remain after testing raw JSON cursor
  decoding. No customer output is stored in this plan.
- Production migration audit: no pending Django or ingest SQL migrations.

## Checkpoint / next action

Finalize staging and diff checks, commit only this logical change, push origin,
immediately request the configured Portainer redeploy, push the secondary
mirror, and verify deployed code/health plus the packaged shadow command.
Record the resulting commit hash without creating a hash-only follow-up commit.

## Preserved unrelated work

Root `.work/backlog.md`, `operations/templates/device_detail.html`, and
untracked root probes predate this task and must not be staged.
