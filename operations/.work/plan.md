# Active Operations implementation plan

Track: **ADR-0010 generic ecosystem completion — Phase E2**

**Status:** E1 deployed; E2 `0.105.2` corrective release ready for deployment.

## Goal

Add deployment-controlled attribute definitions/mappings and typed,
delta-only claim current/history without promoting them over existing typed
effective readers.

## Scope and affected files

- `apps/core/models.py`
- `apps/core/admin.py`
- new additive E2 migration and shared claim projector
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

1. Add definition, mapping, authority-policy, typed claim current/history, and
   withheld-count contracts with tenant-safe constraints and RLS.
2. Seed only approved normalized attributes; unmapped raw fields remain
   restricted and contribute counts, never effective values.
3. Backfill/project claims in bounded batches and append history only when a
   value/support/authority/withdrawal changes. Heartbeat-only collection must
   produce zero claim writes.
4. Expose populated definition/claim evidence read-only, run basic checks, then
   deploy and verify aggregate behavior on the deployed PostgreSQL environment.
5. Serialize migration/backfill against active ingest, or split those
   boundaries, to avoid repeating the recovered 0101 first-start deadlock.

## Validation

- Django system and migration drift checks.
- Disposable PostgreSQL migration/backfill/RLS/uniqueness/grant aggregates.
- Changed-file compile/Ruff and `git diff --check`.
- Deployed version, migration, container health, root HTTP status, and 500 log
  count.

## Checkpoint

`0.104.0` / `5b2e873` was the last healthy deployed release. E2 is implemented:
additive definitions/mappings, independent
authority policies, typed current/per-member history, restricted/count-only
unmapped classification, redacted evidence, bounded post-migration projection,
and guarded 90-day retention. Basic Python, Django, migration-drift, retention,
and diff checks pass; four Ruff findings are pre-existing observation models.
The first `0.105.0` startup applied migration 0102, then 0103 rolled back when
PostgreSQL rejected table DDL with deferred seed constraint triggers pending.
Corrective `0.105.1` forces those checks before RLS/ownership DDL. Migration
0103 then applied; the first projector call wrote no claims and exposed
unqualified `pgcrypto.digest` under the restricted security-definer search
path. Corrective `0.105.2` qualifies the function and replaces the projector
in migration 0104. The user waived further local Docker rehearsal. Next:
commit/push, trigger
Portainer immediately, and verify migrations, aggregate backfill/invariants,
second-pass no-op, health/version, and zero HTTP 500s before starting E3.
