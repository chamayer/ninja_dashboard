# Active Operations implementation plan

Track: **ADR-0010 generic ecosystem completion — Phase E3**

**Status:** E1-E2 deployed; E3 `0.106.0` implemented and locally validated.

## Goal

Add audited single/set operator decisions and a rebuildable, deterministic
effective-value projection over E2 claims without promoting existing typed
consumers yet.

## Scope and affected files

- `apps/core/models.py` and `apps/core/admin.py`
- additive E3 migrations and one shared effective-value projector/service
- focused policy, conflict, audit, and schema tests
- ADR-0010, root `VERSION`/`CHANGELOG.md`, and active plans

## Decisions

- Precedence is explicit: active operator decision, then eligible claims at
  the highest authority tier and priority. Recency is never a hidden
  tie-breaker.
- Single-value equal-authority disagreement creates visible conflict state and
  follows the definition's `retain_last_uncontested` or `unknown` policy.
- Set values use `highest_authority_union` or `all_eligible_union`; operator
  replace establishes the base set and add/remove applies per member.
- Effective current and its supporting-claim references are rebuildable
  projections. Source claims and operator decisions remain independent facts.
- Decision writes are validated, reasoned, and atomically recorded in the
  existing generic `audit_log`; E3 must not create a separate audit silo.
- Existing typed caches/readers remain authorities until a later measured E5
  cutover. Connectors and resolvers do not gain direct effective-value writes.
- All new tenant tables receive forced RLS, tenant policies, tenant-consistent
  constraints, least-privilege grants, and indexes required by the projector.

## Steps

1. Add typed operator-decision current/event contracts, conflict current,
   effective current, and effective-support tables.
2. Implement one deterministic, bounded projector from active E2 claims and
   decisions, including single/set semantics and conflict policy.
3. Add a validated atomic decision-write service that appends the existing
   generic audit log and triggers or queues projection without exposing values
   in logs.
4. Backfill effective state, expose populated engine tables read-only in admin,
   and add aggregate parity/status reporting. Do not add the E5 workflow UI or
   cut over typed consumers.
5. Run basic checks, release, deploy, and verify aggregate invariants,
   deterministic rebuild/no-op behavior, audit/RLS, health, and zero HTTP 500s.

## Validation

- Django system and migration drift checks; focused policy/audit tests.
- Changed-file compile/Ruff and `git diff --check`.
- Deployed aggregate effective/conflict/support counts, RLS/uniqueness, audit
  immutability, deterministic rebuild and immediate no-op behavior.
- Deployed version, migration, container health, root/health status, and recent
  HTTP-500/traceback/error counts.

## Checkpoint and next action

`0.105.4` / `032dc07` is deployed on both remotes with migrations through 0106.
The one-time state-hash refresh processed 30,152 records in seven bounded
transactions and recorded only intervening material deltas. Its immediate
second pass completed in 0.431 seconds with zero processed records or writes.
Production has 30,103 source-current/projection/withheld rows, 266,184 current
claims (266,148 active), and 266,921 history rows (266,148 open). Duplicate,
open-presence, tenant, and definition-shape mismatches are all zero. All five
E2 tenant tables have forced RLS and policies. Version/health/root checks pass
and recent HTTP 500, traceback, and ingest-error counts are zero. The user
waived further local Docker rehearsal.

E3 is implemented locally with typed decision headers/members, database
validation and generic audit triggers, a claim/decision dirty-key queue,
deterministic effective/conflict/member/support projection, a bounded ingest
orchestrator, and a redacted effective-value read/admin model. Existing typed
consumer promotion and the generic decision UI remain in E5. Python compile,
Django check, migration drift, focused Ruff, four contract tests, and diff
checks pass; no local Docker rehearsal was run per the user's validation limit.

Release `0.106.0` / `4d7485f` reached both remotes and Portainer. Migration
0107 applied, then 0108 rolled back cleanly because its initial dirty-key seed
left deferred tenant-constraint triggers pending before ownership DDL. Ingest
remained healthy and no typed consumer was cut over. Corrective `0.106.1`
forces those constraints immediately inside 0108, matching the proven E2
migration pattern. Next: validate, commit, push/deploy/mirror immediately, then
drain the initial dirty queue and verify all planned aggregate invariants.
