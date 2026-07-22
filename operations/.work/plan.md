# Active Operations work plan

Track: **Observation current/history data migration and legacy retirement**

## Status

- In progress. Current/history schema and direct software current writer are
  deployed. Legacy `entity_observations` still holds 3.04M append-cycle rows
  and all three writers still append to it; this is the last storage-growth
  path and blocks retirement.

## Goal

Migrate the retained legacy state into bounded current/history stores, stop
legacy appends, validate runtime readers and cardinality, then truncate the
3.04M-row legacy table while retaining its empty schema only as a compatibility
shell until a later schema-removal migration.

## Scope

- **In:** current-state seed, baseline open-history seed, removal of legacy
  writer calls, production verification, and approved legacy data truncation.
- **Out:** reconstructing prior change intervals from append-cycle payloads;
  the retained baseline is explicitly a starting state and future history is
  change-only. Raw payload history remains deferred.

## Affected files

- `apps/core/migrations/0073_software_installation_history.py`
- `apps/core/management/commands/seed_observation_current.py`
- `apps/core/management/commands/seed_observation_history.py`
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
- The migration seeds one truthful baseline interval per current identity; it
  does not invent historical transitions from heartbeat rows. New writes carry
  forward change-only SCD-2 history from that baseline.

## Steps

- [x] Verify current production cardinality and identify software as the
  high-cardinality relationship set.
- [x] Add dedicated software history schema, indexes, RLS, and direct
  reconciliation SQL.
- [x] Change Ninja software ingest to upsert dedicated current/history and
  reconcile only complete fleet runs.
- [x] Exclude software from generic-current seed; document raw-data deferral.
- [x] Add focused tests and run checks/formatting/migration review.
- [x] Remove the three legacy writer calls and add idempotent baseline-history
  seed tooling.
- [x] Deploy, seed current and baseline history, and validate identity/count
  parity with legacy latest-state queries.
- [x] Truncate legacy rows and confirm no observation writer or reader regresses.

## Validation plan

- Targeted observation tests plus `python manage.py check`, `ruff check .`,
  `ruff format --check .`, and `git diff --check`.
- Compare legacy latest identities to seeded current rows; verify every active
  current row has one open baseline history interval.
- After truncation, verify containers, writer logs, and zero legacy rows.

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

- Stop legacy append writes, deploy seed tooling, and execute the verified
  current/history migration before truncating legacy data.

## Post-deployment hardening (2026-07-22)

- Audit against ADR-0007 identified four gaps between intent and shipped
  code — all closed:
  1. `ingest/observations.py::write_current_rows` now takes a per-tuple
     `pg_advisory_xact_lock` before `SELECT ... FOR UPDATE`, so absent-row
     races between concurrent writers are serialized.
  2. Out-of-order guard drops rows in Python when
     `row.observed_at <= _current.observed_at` (equal timestamps are stale
     to prevent zero-length SCD-2 intervals). SQL upsert mirrors the guard
     with `WHERE _current.observed_at < EXCLUDED.observed_at`.
  3. Bespoke observation upsert (not `db.upsert`) uses `COALESCE` on
     `device_id` / `client_id` so a fresh connector NULL cannot clear a
     resolver-populated value. Python-side preservation also applies.
  4. Nightly retention wired in `ingest/main.py::run_observation_history_prune_once`
     via `retention_observations.purge_all(days=90)` calling the
     security-definer function `operations.purge_closed_observation_history`.
- Also fixed: `write_history_changes` now closes with the prior
  `_current.last_seen_at` (side-banded as `_prior_last_seen_at`), not the
  incoming row's `last_seen_at`.
- Tests: `ingest/tests/test_observations.py` covers out-of-order (older
  and equal-timestamp), resolved-ID preservation, material-change close
  with prior last_seen_at, heartbeat without material change, new
  identity opens first history version, batch sorted by identity before
  locking. `ingest/tests/test_retention_observations.py` asserts the
  retention path routes through the security-definer function and never
  issues raw DELETE. 12 tests pass locally.
- ADR-0007 promoted to v5 with the hardening documented.
