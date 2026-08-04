# Active Operations implementation plan

Track: **ADR-0010 generic ecosystem completion — Phase E4**

**Status:** E1-E3 deployed; E4 implemented and locally validated for `0.107.0`.

## Goal

Add generic relationship evidence/effective edges, activate the generic
candidate/event authority, and capture immutable source-native events including
safe Ninja deletion evidence without promoting the E5 admin/read cutover.

## Scope and affected files

- `apps/core/models.py` and additive E4 migrations
- shared relationship, candidate, and source-event services/projectors
- Ninja activity ingestion only where it emits the generic source-event
  contract; existing immutable activity storage remains compatible
- focused authority, audit, idempotency, withdrawal, and schema tests
- ADR-0010, root `VERSION`/`CHANGELOG.md`, and active plans

## Decisions

- Relationship evidence retains complete source-native endpoint identities and
  may remain unresolved. Unconfigured authority is observed-only.
- Canonical/effective edges are rebuildable from eligible evidence plus audited
  operator include/exclude decisions; withdrawing one source removes only its
  support.
- The existing `entity_candidates` / `entity_candidate_events` pair becomes
  the generic review authority. Current typed review workflows remain behind
  compatibility until E5 can cut their UI/readers over with measured parity.
- Source events are immutable and idempotent by source instance plus vendor
  event identity. Protected source-actor identifiers/display metadata stay out
  of logs, findings text, and aggregate validation.
- A validated, in-order Ninja `NODE_DELETED` event may close matching source
  evidence with reason `source_deleted`; it never deletes or retires the
  canonical entity and a later complete snapshot still corroborates absence.
- Operator relationship/candidate decisions append the existing generic
  `audit_log`; no feature-specific audit silo is introduced.
- All new tenant tables receive forced RLS, tenant policies, tenant-consistent
  constraints, least-privilege grants, and required indexes.

## Steps

1. Add relationship type/policy, unresolved evidence, effective edge/support,
   and audited decision contracts plus one bounded projector.
2. Add generic candidate projection and atomic decision/link-history services;
   preserve typed compatibility readers/actions until E5.
3. Add immutable generic source events and route newly ingested Ninja
   `NODE_DELETED` events through validated source-withdrawal confirmation.
4. Expose only populated engine state read-only where useful; do not add the E5
   operator workflow or generic landing/detail UI.
5. Run basic checks, release, deploy, and verify aggregate invariants,
   idempotent no-op behavior, audit/RLS, health, and zero HTTP 500s.

## Validation

- Django system and migration drift checks; focused authority/audit/event tests.
- Changed-file compile/Ruff and `git diff --check`.
- Deployed aggregate relationship/candidate/event counts, RLS/uniqueness,
  tenant consistency, immutable-event idempotency, and immediate no-op behavior.
- Deployed version, migration, container health, root/health status, and recent
  HTTP-500/traceback/error counts.

## Checkpoint and next action

Corrective `0.106.1` / `7f07124` is deployed on both remotes with migrations
0107-0109 applied. The initial effective projection drained 181,239 dirty keys
in 363 bounded transactions. Production now has 181,239 effective headers,
5,640 set members, 163,304 effective support rows, 168 visible conflicts, and
662 conflict-support rows. The queue is empty and an immediate pass completed
in 0.126 seconds with zero processed records or writes.

Duplicate, tenant/class/type/cardinality, support, typed-value, set-status, and
conflict-flag mismatch counts are zero. All eight E3 tenant tables have forced
RLS and one policy, and the tenant-scoped redacted view has exact row parity.
Decision/audit triggers are enabled; no production decision was fabricated to
exercise them. Version, migrations, services, root/health, remotes, and current
HTTP-500/traceback/ERROR/CRITICAL checks pass. The first 0108 attempt's known
deferred-constraint ordering failure was preventable and is explicitly carried
forward as a migration-review regression rule.

E4 now includes the relationship registry/policy/evidence/decision/dirty-edge/
effective-support contract, generic candidate material-delta projector and
atomic attach/reject services, and immutable restricted source events. New
Ninja activities dual-write temporarily to generic events; `NODE_DELETED` is
always requested. Exact stable identity and event ordering are mandatory before
withdrawal, which closes current/history together and only marks source links
missing. The measured 228 retained deletions all have actor IDs but no device
ID, so no message/hostname inference or historical backfill is bundled. The
initial generic candidate projection is expected to create 4,918 current rows
and one create event each, then become an immediate material/link no-op.

Python compile, Django check, migration drift, focused Ruff, nine E3/E4
contract tests, and diff checks pass. Next: commit, push `origin`, immediately
redeploy through Portainer, push the mirror, then validate migrations, aggregate
candidate/relationship/event/RLS state, no-op behavior, version/health, and
current HTTP-500/traceback/error counts.
