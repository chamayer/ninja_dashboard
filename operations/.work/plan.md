# Active Operations implementation plan

Track: **Corrective Track A — lifecycle evidence and immutable audit**

**Status:** LOCAL RELEASE/DOCUMENTATION CORRECTION PREPARED — deployed inert
schema release commit `434f24d` remains healthy, and local version `0.98.6`,
changelog, ADR-0011, and deployment-gate documentation await review and
separate commit approval. Policy activation remains unauthorized.

## Goal

Make lifecycle selection use explicit, fail-closed registry policy and the
newest qualified evidence. Preserve the deployed automatic three-state model;
keep `retired` operator-only. Record each automatic transition atomically in
the generic audit stream and expose policy/status read-only under **Admin →
System**.

## Scope

- Add `lifecycle_evidence_mode` to the existing registry objects, model them in
  Django state, seed the approved policy, and restrict registry writes.
- Implement deterministic direct-contact and reported-state lifecycle evidence
  selection in the ingest evaluator.
- Add the unknown-lifecycle-state data-quality finding path.
- Harden `operations.audit_log` for append-only runtime access and atomic
  evaluator audit insertion.
- Add the bounded, read-only Admin → System policy/status and lifecycle-audit
  surface using the existing admin shell.
- Add focused unit and PostgreSQL integration tests where the documented
environment supports them.

Out of scope: executing migrations, production queries/changes, broad Admin
navigation work, generic entity redesign, commits, pushes, deployment, and
release cutover/rollback.

## Decisions

- `lifecycle_evidence_mode` is the sole lifecycle capability: `none`,
  `direct_contact`, `reported_state`, `direct_then_reported_state`; database
  default `none`.
- Newest qualified evidence wins. Direct contact wins an exact timestamp tie.
  Recognized powered-off, suspended, and offline states are negative evidence;
  recognized powered-on and online states are positive evidence. Unknown state
  yields a finding and no transition.
- Initial modes: agents use direct contact; `vm.host` uses direct then
  reported state; `vm.guest`, `network.device`, and `monitor.target` use
  reported state; all others default to none.
- `audit_log` is the permanent generic audit landing; runtime roles are
  append-only and the evaluator is insert-only. The future generic entity
  anchor extends the event rather than moving lifecycle events.
- The Track A UI is read-only under **Admin → System** and must reuse shared
  navigation and permissions. Larger Admin UI consolidation remains deferred in
  `operations/.work/backlog.md`.

## Affected files

- `operations/apps/core/models.py` and a new migration after `0092`.
- `ingest/evaluator.py` and focused tests under `ingest/tests/`.
- Operations views, URLs, templates, admin navigation, and tests as required
  for the bounded read-only surface.
- This plan and root `.work/plan.md` coordination checkpoint.

## Steps

1. **Complete:** inspected the deployed-model/migration, evaluator, finding,
   audit, and Admin shell implementation; reconciled the design with current
   code.
2. **Complete:** created migration `0093`, Django registry model state,
   evaluator/audit/finding behavior, and focused tests.
3. **Complete:** added the read-only Admin → System lifecycle policy/status
   and transition-audit surface with tenant context set inside the request
   transaction.
4. **Complete:** Python compilation, Django checks,
   migration-state check, focused tests, targeted Ruff/format checks,
   migration-SQL review, and `git diff --check` passed. With explicit user
   approval, the isolated PostgreSQL 16 container test passed, proving registry
   grants, audit RLS/append-only access, and lifecycle-update/audit atomicity.
5. **Complete:** implementation review found a fail-closed null-power-state
   defect, lifecycle-finding deduplication ambiguity, Admin authorization and
   audit-actionability gaps, incomplete decision-matrix coverage, and stale
   migration documentation.
6. **Complete:** user-approved local correction pass preserved raw power-field
   presence, deduplicated lifecycle findings across active operator statuses,
   used the shared admin permission and Device ID, expanded tests, and
   corrected migration documentation.
7. **Complete:** rereview passed after 12 lifecycle unit tests, the disposable
   PostgreSQL test, 3 Django lifecycle permission/template tests, Django
   checks, migration-state check, targeted Ruff/format checks, and diff check.
8. **Complete:** authorized aggregate-only production preflight returned 343
   projected transitions, 99 unknown reported-evidence rows, 0 equal-time
   conflicts, and 20 eligible devices without qualified evidence; no external
   state changed.
9. **Complete:** user approved the narrow local correction replacing the
   evaluator's `o.id` tie-break with `o.observation_id` and aligning the
   disposable PostgreSQL fixture. Python compilation, targeted Ruff, 12
   lifecycle unit tests, the disposable PostgreSQL test, and diff check passed.
10. **Complete:** the host owner provided a private Operations backup location;
    the corrected exported-snapshot measurement and restricted custom-format
    backup then completed. The exact projected transition set totals 343 across
    seven categories: 38 active→offline-aging direct, 254 active→offline-aging
    reported, 47 active→pending-cleanup direct, 1 offline-aging→active direct,
    1 offline-aging→pending-cleanup direct, 1 pending-cleanup→active reported,
    and 1 pending-cleanup→offline-aging reported. No conflict devices; 18
    eligible devices lack qualified evidence. A follow-up evaluator-equivalent
    live aggregate reconciled unknown states to 99 rows across 99 devices, all
    present-null `vm.host` power fields; the temporary 4,884 result was a query
    defect. No broad service pause was used.
11. **Complete review finding:** independent readiness review found that
    `0093` immediately seeds active lifecycle modes while the same release ships
    the automatically scheduled evaluator. With no lifecycle-only pause, the
    migration and activation gates cannot be separated. Recommended correction:
    leave all modes at default `none` in `0093` and reserve policy seeding for a
    later activation migration/release.
12. **Complete:** user-approved local correction removed policy seeding from
    `0093`; the integration test now asserts the safe `none` state before its
    isolated test-only activation. The later activation migration is recorded
    in the Operations backlog and prohibited from the schema-landing release.
    All focused validation passed.
13. **Complete with approval condition:** rereview found no hidden production
    activation and reconfirmed packaging and validation. Deploying the new
    evaluator with all modes `none` pauses only lifecycle-status automation;
    existing statuses and unrelated ingest/evaluator work remain unchanged.
    Explicit acceptance of that scoped pause is required before the commit
    gate.
14. **Complete:** the user accepted the scoped pause. Prepare, but do not yet
    create, one local Track A schema-landing commit; preserve unrelated dirty
    documentation, decision records, probes, and worktree changes.

## Validation plan

- `python manage.py check`, `python manage.py makemigrations --check`, focused
  pytest, Ruff, template/request checks, migration-plan review, and
  `git diff --check`.
- PostgreSQL integration tests prove registry grants, audit append-only access,
  RLS, and atomic lifecycle-update/audit behavior when the required local stack
  is available.
- No external validation or migration execution without separate authorization.

## Checkpoint

Root plan measurements and the design decision record were verified against the
working tree before implementation. Existing uncommitted changes include
root/Operations documentation and `.work` probe files; they remain preserved.
The prior completed Operations UI redesign plan was replaced as required for
this new nontrivial Operations task. Local Track A edits are limited to the
registry model/migration, evaluator, focused tests, Admin → System lifecycle
surface, and these plans. No migration, database, production, commit, push, or
deployment action occurred.

The 2026-07-31 approval review reverified that checkpoint against current Git
status and files. It demonstrated that a present null VM `power_state` can be
coerced by the existing presence projection to `reported_online = false` and
then selected as offline evidence, contrary to the approved fail-closed rule.
It also confirmed that lifecycle finding upserts can duplicate conditions in
operator statuses outside `open`/`acknowledged`, the new endpoint lacks the
shared admin permission and a Device reference in its transition rows, and the
seven tests do not cover the complete approved decision/permission matrix.
Migration `0092` also retains a stale comment tying lifecycle to
`is_identity_signal`. Review changed only the root and Operations plan
checkpoints; no implementation, migration, database, external, production,
commit, push, or deployment action occurred.

The user then approved a local-only correction pass. It preserves the approved
safe semantics: a present null/unrecognized power field is unknown, never a
legacy offline projection; active lifecycle findings refresh without changing
an operator's `open`, `acknowledged`, `investigating`, or `suppressed` status;
and the read-only audit surface uses the existing shared admin permission and
shows the audited Device ID. Resolved and `wontfix` findings remain historical,
so a later recurrence opens a new row. No migration execution, external
validation, production change, commit, push, or deployment is authorized.

The corrected implementation and rereview passed on 2026-07-31. The
PostgreSQL test specifically proves that a present null power field opens a
finding without transitioning lifecycle, that investigating/suppressed
lifecycle findings refresh without duplication and resolve on recognized
evidence, that retired devices remain unchanged, and that registry/audit
permissions, RLS, and lifecycle-update/audit atomicity hold. The 12 evaluator
unit tests, 3 Django lifecycle permission/template tests, `manage.py check`,
`makemigrations --check`, targeted Ruff/format checks, and `git diff --check`
also passed. Full Ruff on legacy Operations views remains pre-existing outside
this scope. No migration, external validation, production change, commit,
push, or deployment occurred.

The authorized aggregate-only production preflight then confirmed remote
Operations, ingest, and Postgres health and returned only aggregate lifecycle
results. It also exposed a production-schema incompatibility: the evaluator's
lateral raw-observation tie-break orders by `o.id`, but the deployed
`entity_observation_current` key is `o.observation_id`. The first query failed
before returning data; the corrected read-only projection completed and showed
343 total projected transitions, 99 unknown reported-evidence rows, 0
equal-time conflicts, and 20 eligible devices without qualified evidence. No
pause, backup, migration, evaluator run, production write, commit, push, or
deployment occurred. The evaluator query and disposable fixture must be
corrected locally and rereviewed before any migration gate.

The user approved that narrow local-only correction. It changes no behavior
beyond matching the deployed observation primary-key name and changes no
migration, production data, or external state.

The correction and focused rereview passed on 2026-07-31. The evaluator now
orders by the deployed `observation_id` key, and the disposable PostgreSQL
fixture uses that same key, so the integration test exercises the production
query shape. Python compilation, targeted Ruff, all 12 lifecycle unit tests,
the disposable PostgreSQL test, and `git diff --check` passed. No migration,
external action, production change, commit, push, or deployment occurred.

The user then authorized a lifecycle-evaluation-only pause before a fresh
aggregate recapture. Read-only external inspection confirmed that the healthy
ingest container runs `python -m ingest.main` under an `unless-stopped` restart
policy and logged one platform-evaluator completion during the preceding six
hours. The deployed scheduler exposes the evaluator as an in-process job and a
manual run endpoint only; it has no lifecycle-only pause switch, scheduler
control endpoint, or documented external procedure. The only apparent runtime
control would pause or stop the entire ingest service, which also affects
unrelated cycles and is not covered by this authorization. No pause, recapture,
backup, migration, evaluator activation, production data change, commit, push,
or deployment occurred.

The user accepted the cleaner cutover approach: do not pause the whole ingest
service. When separately authorized, capture the final aggregate measurement
and restricted pre-change backup in one short, transactionally consistent
window. This preserves a defensible before-state without interrupting unrelated
ingest cycles.

The subsequent authorized consistent-window attempt made no schema or data
change and retained no backup. After two local query/marker failures stopped
before the measurement completed, the corrected read-only exported-snapshot
measurement completed but the protected dump failed before creation: the
root-owned `/amr-ch-01_data/ninja-dashboard/backups` directory is not writable
by the approved SSH account, and noninteractive sudo is unavailable. The
temporary artifact was removed, the snapshot closed, and no aggregate output
was returned. Host access is now the sole blocker for this prechange step.

The host owner provided the private Operations backup location, and the
corrected repeat completed a restricted custom-format backup and exact
aggregate-only projection under one exported read-only snapshot. Two protected
backup copies are retained because the first accompanied a query duplication
defect; the later copy is the authoritative pair. The transition categories
total 343 as recorded in Step 10. A follow-up evaluator-equivalent live query
reconciled unknown states to 99 rows across 99 devices, all present-null
`vm.host` power fields. The temporary 4,884 result was a projection-query
defect, not a production data change. No migration, evaluator activation,
production data change, commit, push, or deployment occurred.

Independent migration-readiness review reverified the dirty working tree,
current files, prerequisite migration, and backup. Fifteen focused unit/UI
tests, the disposable PostgreSQL test, Django checks, migration-state check,
targeted Ruff/format checks, Python compilation, and diff check passed.
Production is at `0092`; `operations_migrate` owns `entity_types` and
`audit_log`; the authoritative backup checksum matches and its restore catalog
parses. The release is nevertheless not ready for approval because `0093`
immediately activates policy rows and the same deployed ingest image schedules
the evaluator automatically. No lifecycle-only pause exists, so the planned
migration and activation gates are coupled. No implementation or external
state changed during review.

The user approved the local-only cutover correction. Migration `0093` now lands
the lifecycle capability, constraints, finding types, and grants without
activating any entity type. The disposable PostgreSQL fixture first proves the
post-migration `none` state, then applies policy only inside the isolated test.
Fifteen focused unit/UI tests, the PostgreSQL integration test, Django checks,
migration-state check, targeted Ruff/format checks, Python compilation, and
diff check passed. Activation is recorded in the Operations backlog for a later
separately approved migration/release. No external or production state changed.

Fresh rereview confirmed that policy activation appears only in the isolated
PostgreSQL test fixture, all runtime files are packaged, and 15 focused unit/UI
tests, the PostgreSQL integration test, Django checks, migration-state check,
targeted Ruff/format checks, and diff check pass. It also made the remaining
operational consequence explicit: because the new evaluator replaces the
legacy lifecycle sync, all policy modes at `none` pause automatic lifecycle
status updates until the activation release. This does not pause collection,
coverage, or other evaluator work and does not modify existing statuses. No
implementation or external state changed during rereview.

The user explicitly accepted that scoped pause. The next gate is a single local
Track A schema-landing commit; unrelated dirty documentation, decision records,
probes, and worktree changes remain excluded. No files were staged, committed,
pushed, deployed, or migrated while preparing the gate.

The user separately approved the local commit. Commit `434f24d` was created
after final staged validation (15 focused unit/UI tests, disposable PostgreSQL
integration test, Django checks, migration-state check, and staged diff check).
No push, deployment, migration, or production state change occurred. The root
plan remains intentionally uncommitted because it contains unrelated mixed
work; this committed Operations plan is the Track A continuity record.

The separately approved `origin` push was confirmed on 2026-07-31: remote
`origin/master` resolves to `434f24d`. No action was taken against the required
`a-m-rose` secondary mirror. No deployment, migration, or production
validation was requested or performed.

The separately approved secondary-mirror push was then confirmed on
2026-07-31: `a-m-rose/master` advanced from `0557afe` to `434f24d`, matching
`origin/master`. No deployment observation, migration, or production validation
was requested or performed.

The user then authorized read-only deployment observation and live
migration-readiness verification. Ingest and Operations had been rebuilt and
were healthy; Postgres remained healthy and was not recreated. The running
Track A migration/template artifacts matched the local commit byte-for-byte,
and the evaluator matched after normalizing Windows CRLF to Linux LF. Django
migration status showed both `0092` and `0093` applied.

This revealed that the approval model in this plan did not match the deployed
automation. An `origin` push triggers Portainer redeployment, and the Operations
entrypoint applies Django migrations during startup; deployment and schema
application therefore cannot be held as later independent gates after a push.
The inert migration avoided policy activation, but `VERSION` is still `0.98.5`
and `CHANGELOG.md` has no Track A entry despite the shipped runtime, schema, and
Admin surface. No write, migration command, policy activation, or production-
data change was performed during the read-only observation.

The user approved a local-only release/documentation correction. The prepared
correction advances the root release authority from `0.98.5` to `0.98.6`, adds
the missing Track A changelog entry, records the durable decision in ADR-0011,
and documents `origin` push, Portainer redeploy, and automatic startup migration
as one production approval boundary. Version `0.98.6` is not deployed until a
later separately approved commit and push. No implementation code, external
state, production data, migration, commit, push, or deployment changed during
this correction.
Documentation validation passed: root `VERSION` matches the first changelog
entry, ADR-0011 matches the deployed inert behavior, the active instructions
and runbooks consistently describe the coupled GitOps boundary, scoped files
have no trailing whitespace, and `git diff --check` reports no whitespace
errors (line-ending warnings only).

## Next action

Review the local release/documentation correction and obtain separate commit
approval. Finish aggregate inert-policy verification before the later,
separately approved policy activation/reconciliation gate.
