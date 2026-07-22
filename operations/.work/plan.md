# Active Operations work plan

Track: **Production startup hotfix — observation migration compatibility**

## Status

- In progress. The 0070 retired-table guard has reached production and startup
  advanced to migration 0071, which now fails because the renamed legacy
  materialized view retains the new view's intended index name.
- Client-workspace commit `7e61892` is already on both remotes. The push to
  `origin` also included the preceding observation-cutover history; that
  outgoing range was not audited before push and caused this migration failure.

## Goal

Restore Operations startup with forward-compatible migration fixes, without
recreating retired data or rolling back already-applied observation migrations.

## Scope

- **In:** make migration 0070 conditional on
  `operations.identity_candidates` existing; validate migration ordering and
  SQL behavior; rename the legacy source-health index in migration 0071 so the
  replacement view can create its index; inspect deployed restart logs.
- **Out:** recreating `identity_candidates`; rollback; data rebuild; unrelated
  observation-cutover changes; commit, push, and deployment until separately
  approved.

## Affected files

- `apps/core/migrations/0070_identity_candidate_current_reference.py`
- `apps/core/migrations/0071_source_health_current_observations.py`
- `.work/plan.md`

## Decisions

- Migration 0054 is authoritative: `identity_candidates` is retired and must
  not be recreated merely to satisfy migration 0070.
- Migration 0070 remains useful only as compatibility behavior for databases
  where the table still exists. Guard all table operations with `to_regclass`.
- Prefer the forward fix because migrations through 0069 have already applied;
  no destructive rollback is justified.
- PostgreSQL index names do not change when a materialized view is renamed.
  Migration 0071 must rename the legacy index before creating the replacement
  view's index and restore the name on reverse.

## Steps

- [x] Capture deployed container traceback and identify the failing migration.
- [x] Confirm migration 0054 intentionally dropped the referenced table.
- [x] Guard migration 0070 for both retired-table and compatibility cases.
- [x] Rename the legacy source-health index in migration 0071 and reverse SQL.
- [x] Run Django migration plan/checks, Python/Ruff checks, and diff review.
- [ ] Obtain separate approval for commit and push/deployment.
- [ ] After deployment, verify migrations, health, routes, and container logs.

## Validation plan

- `python manage.py check`
- `python manage.py showmigrations operations --plan` where available
- Python compile and Ruff for migration 0070
- Review SQL against both `to_regclass(...) IS NULL` and present-table paths
- `git diff --check`

## Checkpoint

- `ninja-operations` repeatedly fails while applying 0070 with
  `UndefinedTable: relation operations.identity_candidates does not exist`.
- Migration 0054 explicitly dropped that table and removed its Django model.
- Logs show 0070 is not applied; the migration transaction rolls back on each
  restart. Migrations through 0069 are already past the executor checkpoint.
- Local `master` and `a-m-rose/master` contain one additional concurrent
  observation commit (`359be28`). The uncommitted recovery is isolated on
  `hotfix/operations-startup` based directly on `origin/master` at `7e61892`,
  so that additional commit cannot enter the primary recovery push.
- Concurrent commit `27b3037` containing the 0070 guard was pushed to `origin`
  outside this session's approval flow. GitOps rebuilt the container; 0070 then
  applied successfully and startup advanced to 0071.
- Migration 0071 currently rolls back with
  `DuplicateTable: relation idx_source_health_current_pk already exists`.
  Renaming the view retained its index name, colliding with the replacement
  view's `CREATE UNIQUE INDEX` statement.
- Migration 0071 now renames `idx_source_health_current_pk` to
  `idx_source_health_current_legacy_pk` immediately after renaming the legacy
  view. Reverse SQL restores both names. Python compilation, Django check,
  Ruff check/format, and `git diff --check` pass for this extension.
- Migration 0070 now wraps every operation on `identity_candidates` inside a
  `to_regclass(...) IS NOT NULL` guard. The nested current-observation FK and
  backfill remain available only when both compatibility tables exist.
- Validation: Python compilation, `python manage.py check`, Ruff check/format,
  migration graph/plan loading, and `git diff --check` pass. Local
  `makemigrations --check --dry-run` reports a pre-existing model-state drift
  that would generate migration 0073; it is unrelated to this SQL-only hotfix
  and must not be folded into the outage recovery.

## Next action

- Finish and validate the conditional migration. Present the diff and safe
  commit/push strategy for separate approval.

## Cross-service pointer

The observation redesign authority remains the repository-root `.work/plan.md`
and `docs/decisions/0007-observation-model-content-hashed-current-plus-history.md`.
This Operations UI plan does not modify or supersede that track.
