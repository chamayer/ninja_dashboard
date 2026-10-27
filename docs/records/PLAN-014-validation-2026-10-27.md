# PLAN-014 — Local reconciliation validation

Historical evidence for the earlier repair. The later expanded build is
recorded in [the build checkpoint](PLAN-014-build-2026-10-27.md); its validation
was deferred by the user. Counts below do not validate the later build.

Date: 2026-10-27. Status: local requirement reconciliation passes its focused
checks; overall plan remains active. No commit, push, deployment, production
recalculation, migration or production data change was performed.

## Scope and confirmed implementation

The current `ingest/evaluator.py` patch reconciles existing requirement
findings from the successful coverage pass's verdicts, in the same
transaction. It removes the separate profile-resolution SQL and fixed
48-hour closure rule. Obsolete findings receive current assessments before
closure; source, identity, offline, suppression and snooze guards remain in
force. Unknown-OS and cleanup requirement episodes retain their history.
Single-Computer OS recovery is included. The Hudu tests now use profile
items instead of ignored legacy global requirement rows.

## Executed validation

All PostgreSQL integration tests below ran with
`RUN_POSTGRES_INTEGRATION_TESTS=1` against disposable PostgreSQL 16 containers
with synthetic data. They were not skipped and did not use production data.

| Batch | Files / coverage | Result |
| --- | --- | --- |
| Ingest | `test_requirement_reconciliation_postgres.py`, `test_evaluator_requirement_state_postgres.py`, `test_evaluator_os_unknown_coverage_postgres.py`, `test_requirement_state.py`, `test_evaluator_requirement_overrides.py`, `test_condition_safety_contract.py`, `test_evaluator_lifecycle.py`, `test_evaluator_lifecycle_postgres.py`, `test_evaluator_lifecycle_single_transition_postgres.py` | 95 passed |
| Cross-domain contract | `test_requirement_lifecycle_contract.py` | 11 passed |
| Operations | `test_migration_0304_postgres.py`, `test_migration_0332_postgres.py`, `test_migration_0333_postgres.py`, `test_coverage.py` | 42 passed |

The 26 new reconciliation cases use real coverage SQL, the 0332 verdict
writer, real assessment/participant SQL from migrations 0161/0163/0166,
and the policy engine with the 0296/0320 policy builders. They cover:

- 24-hour staleness versus the former 48-hour resolver; stable repeated runs.
- Recovery across open, acknowledged and investigating findings.
- Collection, identity, offline, suppression and snooze guards; later recovery.
- Removed profiles, unsupported OS, exemptions, retirement and leaving coverage.
- Retained unknown-OS and cleanup episodes; single-Computer OS recovery.
- Exact entity/platform and superseded condition keys; missing/stale transitions.
- Wildcard requirements, full-fleet versus single-Computer scope, runtime-role
  tenant isolation, and atomic rollback after a reconciliation failure.

Additional checks passed: focused Ruff, Python compilation, Django
`manage.py check` with the repository root on `PYTHONPATH`, plan registry
validation (24 entries), VERSION/CHANGELOG agreement and `git diff --check`.
The first Django invocation lacked the root import path; rerunning with the
correct local environment passed. No release files were changed.

## What passing tests do not establish

The shared offline authority proposal is **not implemented or validated end
to end**. The existing offline producer and coverage offline guard still
use their old contact/collection calculation. The new cross-domain tests
verify input distinctions and existing lifecycle rules, not a completed
replacement producer. Shared finding-state triggers/cover and requirement
reconciliation are tested in separate harnesses, not one full deployed stack.
No browser, production performance, concurrency stress, or post-deployment
recalculation acceptance is claimed.

The root `BLUEPRINT.md` is 6,550 bytes against the governance workflow's
4,000-byte limit. It was already modified before this repair and was not
changed by this validation. Registry validation passing does not mean the
complete governance workflow passes. Preserve its unrelated checkpoint
content when repairing that separate size issue.

## Offline design acceptance gates

The user approved consolidating offline authority under canonical lifecycle.
That approval does not establish `pending_cleanup` as a synonym for offline.
Before replacing either consumer, share the evaluated reason, qualified
evidence and currentness, and verify:

1. Contact aging produces offline; collection time alone never establishes
   device contact. A current explicit reported state retains its distinct
   meaning. Client thresholds and exact boundaries remain effective.
2. Documentation-only, stopped-VM, archived and nothing-listed cleanup use
   their established cleanup reasons/findings; retired Computers remain out
   of current requirements. Operator-confirmed use must be handled explicitly.
3. Missing/conflicting evidence cannot validate an old lifecycle label.
4. Full and single-Computer runs generate and clear the same appropriate root
   findings, cover and verdicts; recovery and repeat runs preserve history.
5. Failure/partial collection cannot grant clearing authority; policy freshness,
   tenant boundaries and operator handling remain enforced.

Authority conflict to resolve explicitly: ADR-0032 and `computer_listing.py`
describe `confirmed_in_use` as returning to coverage while retaining review
status, but ADR-0036 and the current coverage gate exclude all
`pending_cleanup` Computers. The current repair does not silently add an
exception or claim this scenario is accepted end to end.

## Production acceptance

The earlier authorized read-only checks corroborated 659 distinct drift
entries. They are diagnosis evidence, not evidence that this uncommitted
patch fixed production. The 48 cleanup-verdict disagreements concern 23
Computers with recent ScreenConnect collection and null ScreenConnect
contact timestamps; none had `in_use_confirmed=true`. No active offline or
missing-source parent was found for them. The other root-cause groups and
covered totals are retained in `ingest/BLUEPRINT.md`.

After local offline integration and acceptance tests, review the complete
patch and pending migrations before separately approving commit and push.
Production recalculation needs its own authorization. Close PLAN-014 only
after a current run has zero unexplained drift, with deliberately retained
guarded episodes separately explained rather than overwritten or hidden.
