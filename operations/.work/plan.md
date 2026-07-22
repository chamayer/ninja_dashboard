# Active Operations work plan

Track: **Dedicated software installation current and history**

## Status

- In progress. Generic observation current/history is deployed for non-software
  sources. Software still dual-writes the legacy observation stream and generic
  observation tables, then rebuilds `software_installations_current`; that
  yields roughly 427k device/software identities and makes generic state carry
  a relationship inventory it is not intended to own.

## Goal

Make `software_installations_current` the direct current-state store and add
`software_installation_history` for SCD-2 install/change/removal history,
without losing the existing software UI/query contract or prematurely removing
the legacy observation stream.

## Scope

- **In:** migration for dedicated history, tenant/RLS grants, direct Ninja
  software writer, complete-snapshot staleness/history reconciliation,
  generic-seed exclusion, tests and deployment validation.
- **Out:** retaining raw payloads in the dedicated history (deferred), deleting
  legacy `entity_observations`, and historical backfill before the direct
  writer is verified in production.

## Affected files

- `apps/core/migrations/0073_software_installation_history.py`
- `apps/core/management/commands/seed_observation_current.py`
- `../ingest/inventory/software.py`
- `../ingest/tests/test_software_inventory.py` (if present/new)
- `.work/backlog.md`, `.work/plan.md`

## Decisions

- Software is a device-to-product relationship inventory, not a generic
  source-scoped entity. It keeps a dedicated current table and receives its
  own history table; generic observations remain appropriate for device-like
  source state.
- Dedicated history records material install state only (publisher, version,
  location, install date) plus presence intervals. Raw payload retention is
  deferred; no raw JSON is duplicated in the new high-cardinality history.
- A full fleet snapshot alone may mark absent installs stale and close their
  open history. Scoped (`df`) runs only upsert seen rows and never reconcile
  absence globally.
- Legacy append writes remain during the rollout for rollback compatibility.
  The generic software current/history write and refresh-function dependency
  are removed from the writer once the dedicated path is in place.

## Steps

- [x] Verify current production cardinality and identify software as the
  high-cardinality relationship set.
- [x] Add dedicated software history schema, indexes, RLS, and direct
  reconciliation SQL.
- [x] Change Ninja software ingest to upsert dedicated current/history and
  reconcile only complete fleet runs.
- [x] Exclude software from generic-current seed; document raw-data deferral.
- [x] Add focused tests and run checks/formatting/migration review.
- [ ] Commit, push both remotes, confirm GitOps rollout and live data shape.
- [ ] Seed current state only after deployment validation; plan historical
  backfill separately with an explicit retention window.

## Validation plan

- Targeted software inventory tests plus `python manage.py check`, `ruff check
  .`, `ruff format --check .`, and `git diff --check`.
- Review migration SQL for tenant GUC/RLS and full-versus-scoped reconciliation.
- After GitOps deploy, verify migrations, healthy containers, writer logs, and
  counts for dedicated current/history without a generic-software increase.

## Checkpoint

- Production has 3,041,917 legacy observation rows, 8,279 generic current and
  history rows, and three snapshot runs. A dry-run generic seed found 441,003
  identities, including 426,915 software device/name identities; non-software
  is about 14,088 identities.
- The generic writer path is healthy after the JSON adaptation and snapshot-run
  hotfixes. No legacy-to-current seed or history backfill has been executed.
- Migration 0073 adds current material hashes and a dedicated RLS-protected
  history table. The direct writer preserves legacy writes for rollback, no
  longer writes generic software state, and only reconciles absence after an
  unscoped successful fleet run. Focused hash tests pass (3); Django check,
  Ruff, formatting, and diff checks pass. The test runner only warns that its
  workspace cache cannot be created.

## Next action

- Review the staged diff, commit and push both remotes, then confirm GitOps
  deployment before running any current-state seed.
