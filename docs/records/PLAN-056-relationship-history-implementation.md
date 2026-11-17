# PLAN-056 — Relationship-history equality guard

## Scope and authority — 2026-11-11

The user approved the second proposed implementation slice, then separately
approved focused synthetic PostgreSQL tests. Based on HEAD `ca00938a`, local
changes are limited to the history synchronization predicate in
`ingest/relationships.py:resolve_current_evidence` and the new
`operations/apps/core/tests/test_relationship_history_postgres.py`.
Earlier Coverage and unrelated working changes remain preserved. No commit,
push, release, migration, configuration change or external execution is approved
by these implementation/test approvals.

## Behavior and contract review

The existing UPDATE now includes a six-column `ROW(...) IS DISTINCT FROM
ROW(...)` predicate. It copies source entity, target entity, resolution status,
authority eligibility, tier and priority only when at least one differs.
Nullable endpoint comparisons are null-safe. Both-null endpoints compare equal.

The nonzero-current-resolution gate, returned resolved count, tenant/current-ID
join and open-history filter remain unchanged. Repair still includes visible
stale open history outside the current invocation's changed endpoint IDs. Current
evidence resolution, validation, authority selection, version updates, dirty
queue triggers, source timestamps, material hashes and history intervals are
unchanged. No other relationship writer is included in this correction.

Reviewed migrations 0111–0113 and 0115 for current validation/queue triggers,
open-history uniqueness/window constraints and forced history RLS/grants.
Migration 0306 classifies current evidence as `own_history` and its history table
as `history_store`; no history UPDATE side effect requiring equal assignments
was found in repository definitions. This implements the existing contract;
no new architectural decision or migration is needed. The ingest Dockerfile
already copies the complete `ingest/` directory for both ingest and Jobs paths.

## Actual validation

- **10 new PostgreSQL cases pass**, using one disposable PostgreSQL 16
  testcontainer with a few synthetic rows per case. The full resolver runs
  through a test transaction adapter under `ninja_ingest`, with forced tenant
  RLS on current/history tables and the existing migration 0111 current-evidence
  validation and queue functions/triggers installed unchanged.
- Checks cover suppression of equal history UPDATEs (physical tuple identity and
  complete stored row unchanged), repair of each of the six fields outside the
  changed endpoint population, both nullable endpoints in both transition
  directions, unchanged closed and other-tenant history, preserved dirty-queue
  behavior, and the existing zero-resolution gate. Complete row comparisons
  also retain material hash and effective interval fields.
- **Six existing generic relationship contract checks pass.** Combined targeted
  pytest result: 16 passed.
- Python compilation and Ruff lint pass for runtime/test files; the new test
  module passes formatting. No existing test file was changed.
- Final registry, whitespace, local-link and handoff-size checks are recorded
  in the active handoff. Testcontainer cleanup leaves only preexisting local
  development containers.

The fixture uses minimal input tables, not a full migrated application database;
it does not certify every deployed constraint or production policy. No fleet
processing, timing comparison, production execution or performance claim was
made. Actual write-volume and platform/page benefit remain unmeasured.

## Checkpoint and next action

Local implementation and focused validation are complete. Review this slice
separately from Coverage and preserved work before commit approval. Release/push
review must identify selected contents and pending migrations explicitly. Live
validation needs bounded approval; resource interaction stays deferred under
root TODO.md. PLAN-056 remains active. Revert only this predicate if needed;
preserve the broad repair and unrelated work. Deployment/rollback retain their
separate authorization requirements.
