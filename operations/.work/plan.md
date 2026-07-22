# Active Operations work plan

Track: **Restore device agent presence after observation-store cutover**

## Status

- Deployment validation found an omitted dependency: `v_device` depends on
  `device_session_current`. Migration 0076 rolled back atomically before any
  schema change. Corrective migration work is in progress; commit, push,
  redeploy, and migration application remain authorized.

## Goal

Restore `device_agent_presence_current` so device Identity pages, evaluator
reads, and source-health reach calculations use active rows from
`entity_observation_current`, not the empty compatibility table
`entity_observations`.

## Scope

- **In:** one forward migration, required derived-object dependency rebuilds,
  focused migration and Django validation, and a backlog entry for the broader
  materialized-view suitability decision.
- **Out:** applying the migration, retiring the compatibility table, changing
  public interfaces, or deciding whether presence should eventually be a plain
  view.

## Affected files

- `apps/core/migrations/0076_device_agent_presence_current_observations.py`
- `.work/plan.md`
- `.work/backlog.md`

## Decisions

- Preserve the existing materialized-view shape for the hotfix. A broader
  ADR-level review must decide which observation-derived state merits
  materialization under ADR-0007.
- Use `entity_observation_current` rows where `active` and non-software;
  retain the established device join and public presence columns.
- Rebuild every PostgreSQL derived object that has an OID dependency on the
  replaced presence matview; verify the exact dependency graph first.

## Steps

- [x] Recover the interrupted-session intent and verify the working tree.
- [x] Read applicable architecture and operational guidance.
- [x] Inspect the live derived-object dependency graph (read-only).
- [x] Add and review the dependency-safe migration.
- [x] Add the deferred materialization review to the Operations backlog.
- [x] Run migration-plan and focused local validation.
- [x] Rebuild `v_device` in the same atomic swap and revalidate the rendered
  forward and reverse migration SQL.

## Validation plan

- Confirm the migration plan is linear and the SQL preserves columns, indexes,
  grants, ownership, and refresh order.
- Run `python manage.py check`, `ruff check .`, `ruff format --check .`, and
  relevant focused tests where available.
- Do not run state-changing deployed-stack actions without separate approval.

## Checkpoint

- The observed production symptom is an empty "Where this device is known"
  card; the device Identity tab also returned 500 but that is not yet shown to
  share this root cause.
- `device_agent_presence_current` still selects from the empty legacy
  `entity_observations` table, while the active observation pipeline writes
  `entity_observation_current`.
- The previously completed navigation plan was stale relative to this task;
  the root cross-service observation plan is also historical and does not
  reflect the implemented 0063--0075 cutover migrations.
- Read-only production dependency inspection confirmed that
  `device_session_current`, `source_health_current`, and
  `source_health_current_legacy` depend on the old presence matview by OID.
  The migration rebuilds the two current objects and deliberately retains the
  legacy health object on the legacy presence matview as rollback evidence.
- Validation passed: `git diff --check`; focused Ruff check and format check
  for migration 0076; `python manage.py sqlmigrate operations 0076`; and
  `python manage.py check`. Repository-wide `ruff check .` and
  `ruff format --check .` remain non-green because of pre-existing unrelated
  violations/reformatting in 41 and 9 files respectively.
- Deployment attempt: the new Operations image started and migration 0076
  began, but PostgreSQL rejected `DROP MATERIALIZED VIEW
  device_session_current` because `operations.v_device` depends on it. Django
  migrations run this SQL transactionally, so the failed operation rolled
  back; migration 0076 remains unapplied.
- Corrective migration change: `v_device` is now dropped before the dependent
  session matview and recreated, with its security-invoker option, grants,
  owner, and current patching-scope projection preserved. Focused lint,
  formatting, diff, forward/reverse SQL rendering, and Django checks pass.

## Next action

- Commit the corrective migration update, push to both approved remotes,
  redeploy, and validate migration 0076 plus tenant-aware presence results.
