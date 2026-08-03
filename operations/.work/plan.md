# Active Operations implementation plan

Track: **ADR-0010 generic ecosystem completion — Phase E1**

**Status:** implementation validated; `0.104.0` release pending.

## Goal

Add the rollback-safe generic entity/source-link foundation without promoting
it over existing typed Client/Device and compatibility link authorities.

## Scope and affected files

- `apps/core/models.py`
- `apps/core/admin.py`
- `apps/core/migrations/0101_generic_entity_source_link_kernel.py`
- ADR-0010, root `VERSION`/`CHANGELOG.md`, and active plans

## Decisions

- Existing Client and Device UUIDs remain stable. Each receives one nullable,
  unique generic entity anchor backfilled in migration; it is not required or
  promoted in E1.
- Entity scope is enforced by an entity-class/scope registry and client-owner
  check. Client anchors are tenant-scoped; device anchors are client-scoped.
- Generic source links key the complete ADR-0009 stable source identity and are
  backfilled only from observations already carrying a resolved client/device.
  Unresolved evidence receives no inferred attachment.
- Candidate current/event tables are created for the later engine, but their
  admin pages remain hidden until E4 produces real state, per the engine-first
  UI rule.
- Current links and history are separate. E1 is a shadow foundation; existing
  client/device links remain compatibility authorities until later parity and
  cutover.
- All tenant tables receive RLS, explicit tenant policies, tenant-qualified
  unique targets, least-privilege grants, and indexes needed for current/open
  lookup. Registry mutation remains migration-controlled.

## Steps

1. Add Django models and an additive migration with registry seed/backfill.
2. Expose registries, entities, source links/history, and candidates/events in
   Django admin as read-only operational evidence where appropriate.
3. Run basic checks and one PostgreSQL 16 migration rehearsal.
4. Release as `0.104.0`, deploy, and perform basic health/500 verification.
5. Continue to root Phase E2 after a healthy deployment.

## Validation

- Django system and migration drift checks.
- Disposable PostgreSQL migration/backfill/RLS/uniqueness/grant aggregates.
- Changed-file compile/Ruff and `git diff --check`.
- Deployed version, migration, container health, root HTTP status, and 500 log
  count.

## Checkpoint

E1 is implemented and passes Django checks, migration drift, focused
compile/Ruff checks, and exact forward/backward PostgreSQL 16 rehearsal. The
fixture verified two anchors, two current links, two open history intervals,
all five forced RLS policies, and zero second-pass writes. Release/deploy
`0.104.0`, verify aggregate production backfill plus basic health/500 state,
then hand root coordination to Phase E2.
