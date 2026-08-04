# Active root implementation plan

Track: **ADR-0010 generic entity, claim, relationship, and admin completion**

**Status:** full remaining plan approved; Phases E1-E3 deployed, Phase E4 implemented locally.

## Authority and checkpoint

- The user authorized autonomous implementation, commits, both pushes, and
  their coupled Portainer deployments. Validation should remain basic and
  proportional: syntax/static checks, migration consistency, and basic
  deployed version/health/HTTP-500 and aggregate behavior checks. The user
  explicitly waived further local Docker rehearsal for this phase.
- Release `0.103.0`, commit `0f32922`, is deployed on both remotes. All enabled
  collector families use the generic source-record current/change-history
  contract. The verified cycle wrote zero legacy Ninja detail/health snapshots.
- Existing unrelated backlog, instruction, design, and probe-file changes are
  preserved and excluded from release commits.
- Agent Compliance redesign/cleanup and legacy Ninja historical deletion/disk
  reclamation remain explicitly excluded. Existing typed patch, software,
  immutable activity, audit, notification, finding, and run-ledger semantics
  remain distinct from accidental poll-copy storage.

## Production sizing findings (aggregate-only, read-only)

- Generic source storage contains 30,088 stable current records, 29,240 active,
  57,955 retained material intervals, 341,130 daily rollup rows, and 695 compact
  snapshot-run rows. The measurement returned no identities or payload values.
- Expanding normalized top-level scalar/set members produces 428,425 current
  claim rows (417,931 active). Per-record claim medians are 5-20 by contract;
  p95 is at most 21 for the large namespaces and the measured maximum is 46.
- Attribute-level comparison, excluding unchanged projection-contract-only
  intervals, found 50,107 changed claim members in the latest seven-day window.
  Because Ninja health existed for only part of that window and rollout changes
  are recent, use a conservative 7,200-10,000 changed-member/day envelope.
- Projected claim-history additions are 216k-300k at 30 days, 648k-900k at
  90 days, and 2.63m-3.65m at 365 days. With a deliberately conservative
  256-512 bytes per heap-plus-index row, current claims require about
  105-209 MiB; history requires 53-147 MiB at 30 days, 158-440 MiB at 90 days,
  and 642 MiB-1.74 GiB at 365 days. WAL remains an estimate until a disposable
  scale benchmark: roughly 2-4x changed indexed bytes, or about 1.3-7.0 GiB at
  the 365-day envelope.
- Existing physical totals are 182.6 MiB generic current, 70.8 MiB generic
  history, 45.5 MiB daily rollup, and 0.7 MiB snapshot runs. Typed stores are
  materially larger but semantically intentional: activities 7.02 GiB, patch
  facts 864.6 MiB, software current 1.46 GiB, and software history 445.7 MiB.
- Initial claim history does not justify partitioning below four million rows
  per year. Use identity/open-interval B-tree indexes plus a time BRIN, retain
  closed claim history for 90 days in line with source material history, and
  retain compact daily rollups for at least 365 days. Revisit partitioning at
  10 million retained rows or sustained 25,000 changed members/day.
- Claim current rows must not receive heartbeat writes. They change only when
  an attribute value, supporting evidence, authority, or withdrawal changes;
  last receipt/contact remains inherited from the source-record current row.

## End-state acceptance

1. Every canonical client/device has a stable generic entity anchor without
   changing existing typed IDs or foreign keys.
2. One authoritative generic source link maps each attached stable source
   identity to an entity; compatibility links remain until all readers cut over.
3. Deployment-controlled definitions and mappings produce typed, sensitivity-
   classified current claims and attribute-delta history without per-poll
   duplication. Unmapped fields default restricted and remain visible by count.
4. Authority policy and audited operator decisions produce one rebuildable
   effective-value contract. Equal-authority conflicts are visible and never
   silently broken by recency.
5. Relationship evidence, canonical edges, decisions, candidates/events, and
   source-native events preserve provenance and withdrawal independently.
6. Generic read models and Operations admin pages expose entities, sources,
   evidence, claims/conflicts/effective values, candidates, relationships, and
   source health without source-name template branches.
7. Existing typed device/session/patch/software consumers move only when their
   effective projections have measured parity. Compatibility columns/tables
   and destructive cleanup remain separate final contracts.

## Delivery phases

### E1 — Generic entity and source-link kernel (`0.104.0`, complete)

- Add entity-class/scope registries and the tenant-scoped generic entity anchor.
- Add nullable unique entity anchors to Client and Device, backfill them while
  preserving typed primary keys, and keep typed tables authoritative.
- Add generic source-link current/history and generic candidate current/events.
  Backfill links from exact stable observation identity plus existing resolved
  client/device compatibility IDs; unresolved evidence remains unattached.
- Expose populated registries/entities/links read-only; keep empty candidate
  admin pages hidden until the E4 engine exists, per the engine-first UI rule.
- Expand entity-type capabilities required by ADR-0010. Add read-only Django
  admin visibility. Apply RLS, tenant-consistent uniqueness, least-privilege
  grants, and additive rollback-safe constraints.

### E2 — Attribute definitions and delta claims (`0.105.4`, complete)

- Add versioned attribute definitions, source-field mappings, identity/
  attribute authority policies, typed current/history claims, and withheld
  classification counts.
- Seed the normalized fields required for identity, lifecycle, session,
  operating-system, source health, and CMDB evidence; all unmapped fields are
  restricted and counted rather than silently trusted.
- Backfill roughly 428k current claims in bounded batches. Project only changed
  attributes on later material transitions; do not update claims for heartbeat-
  only polls. Add 90-day closed-history retention and threshold monitoring.

### E3 — Effective values and operator decisions

- Add audited single/set operator decisions, conflict rows, effective current
  values, and supporting-claim references.
- Implement deterministic policy selection: operator decision, authoritative
  eligible claims, then lower-tier claims. Equal-authority single conflicts use
  the definition policy (`retain_last_uncontested` or `unknown`).
- Add one projector and parity reports; connectors/resolvers may not write
  effective typed cache fields directly after promotion.

### E4 — Relationships, candidates, and generic source events

- Add relationship type/policy registries, unresolved external relationship
  evidence, canonical edges, supporting evidence, and audited include/exclude
  decisions.
- Promote candidate current/events to the generic review authority and migrate
  existing identity/client candidate workflows through compatibility views.
- Add immutable generic source events. Implement Ninja `NODE_DELETED` capture
  with protected actor metadata and source-withdrawal confirmation; never
  auto-retire a canonical entity.

### E5 — Generic read/admin surface and consumer cutover

- Add tenant-safe entity summary, source evidence, claim/conflict/effective,
  relationship, candidate, and source-health read models.
- Add Operations Admin landing/detail surfaces driven by registries, including
  restricted-value redaction and permission-checked audited reveal.
- Repoint APIs, exports, findings, notifications, evaluators, and approved typed
  readers to the shared effective contracts. Verify aggregate parity per reader.

### E6 — Contract and operational follow-up

- Make Client/Device entity anchors required only after full parity. Retire
  competing attachment authority and obsolete compatibility columns/readers in
  separately reviewable contract migrations.
- Keep Agent Compliance retirement and Ninja snapshot archive/delete/reclaim as
  independent backlog operations with their own backup/restore and destructive
  approvals. Audit/event retention and fleet-wide audit UI remain their defined
  follow-up tracks where not completed by E4/E5.

## Next E4 scope

- Add deployment-controlled relationship types and authority policy, unresolved
  source relationship evidence, canonical/effective edges and support, and
  audited include/exclude decisions.
- Activate the existing generic candidate/event foundation as the review
  authority while preserving current typed workflows until their measured
  compatibility cutover.
- Add immutable generic source events and route Ninja `NODE_DELETED` through
  the common event/withdrawal contract without retiring canonical entities or
  exposing protected source-actor metadata.
- Update root/Operations plans, ADR-0010 progress, `VERSION`, and
  `CHANGELOG.md` with the implemented E4 contract.

## Basic validation and deployment

- `python manage.py check`, `makemigrations --check --dry-run`, targeted Python
  compile/Ruff/tests on changed files, and `git diff --check`.
- Verify aggregate relationship/candidate/event counts, RLS/policies,
  uniqueness and tenant consistency, decision audit triggers, idempotent event
  capture, and safe deletion-event withdrawal behavior.
- Commit only E4 release files, push `origin`, immediately trigger Portainer,
  push the identical commit to the mirror, then verify its version, migration
  application, service health, expected root status, and zero HTTP 500s.

## Current checkpoint and next action

Phase E1 is deployed as `0.104.0` / `5b2e873` on both remotes. Migration 0101
is recorded; production has 5,336 anchors, 24,924 current links and the same
number of open attachment intervals, with zero unanchored typed records,
duplicate stable links, or tenant/class mismatches. All five tables have
forced RLS and policies. Operations/ingest/Postgres are healthy, root/health
return 302/200, and there are zero HTTP 500 or ingest error markers. The first
Operations start deadlocked during 0101; its normal restart applied the
migration successfully and no recurring error remains.

E2 is deployed. The first `0.105.0` deployment applied
migration 0102, then PostgreSQL rejected 0103 table DDL while its newly seeded,
initially deferred foreign-key triggers were pending. The transaction rolled
back cleanly. Corrective release `0.105.1` validates those deferred constraints
before table-level RLS/ownership DDL. Migration 0103 then applied; its first
accelerated projector call wrote no claims and exposed unqualified
`pgcrypto.digest` under the restricted security-definer search path.
Corrective `0.105.2` proved that `pgcrypto` is not installed. Production
catalog measurement confirmed PostgreSQL's built-in
`pg_catalog.sha256(bytea)` is available; corrective `0.105.3` uses it without
adding a dependency and replaces the projector through migration 0105. The
full backfill then completed at 30,097 source records and 266,113 current/open
claim intervals. The immediate no-op exposed avoidable full-JSON re-hashing;
corrective `0.105.4` reuses the stored source `material_hash` plus version/link
metadata and replaces the projector through migration 0106.
Definitions/mappings and independent authority policy are deployment-controlled;
unmapped fields are restricted/count-only; current claims and per-member SCD-2
history are projected in separately committed bounded batches after migration;
heartbeat/contact timestamps remain on source current and do not create claim
writes. Basic Python, Django, migration-drift, retention, and diff checks
passed; the only Ruff findings were four pre-existing observation models
outside E2.

Corrective `0.105.4` / `032dc07` is on both remotes and deployed. Migrations
0104-0106 are applied and the one-time projection-hash refresh completed in
seven bounded transactions across 30,152 processed records. It recorded only
real intervening deltas: 71 inserted, 737 updated, and 36 withdrawn claims;
808 history intervals opened and 773 closed. The immediate steady-state pass
completed in 0.431 seconds with zero processed records or writes. Production
now has 30,103 source-current/projection/withheld rows, 266,184 current claims
(266,148 active and 36 withdrawn), and 266,921 history rows (266,148 open and
773 closed). There are zero duplicate current members, duplicate open
intervals, active/open-presence mismatches, tenant mismatches, or definition
type/cardinality mismatches. All five E2 tenant tables have forced RLS and one
tenant policy. Version is `0.105.4`; Postgres, ingest, and Operations are
healthy; root/health return 302/200; recent HTTP 500, traceback, and ingest
error counts are zero.

E3 is deployed as corrective release `0.106.1` / `7f07124` on both remotes.
The initial `0.106.0` deployment applied 0107, then PostgreSQL rejected 0108
because its initial dirty-key seed left deferred tenant constraints pending
before ownership DDL; the transaction rolled back and no typed consumer had
been cut over. Corrective 0108 forces the constraints before that DDL, and
migrations 0107-0109 are now applied.

The bounded initial projection completed in 363 transactions over 181,239
entity/attribute keys, producing 181,239 effective headers, 5,640 set members,
163,304 effective support rows, 168 visible conflicts, and 662 conflict-support
rows. The durable queue is empty; an immediate pass completed in 0.126 seconds
with zero processed records or writes. Duplicate, tenant/class/type/cardinality,
support, typed-value, set-status, and conflict-flag mismatch counts are all
zero. All eight E3 tenant tables have forced RLS and one tenant policy; the
tenant-scoped redacted view has exact 181,239-row parity. No operator decisions
exist yet, so production audit triggers were verified from the enabled catalog
contract without fabricating a customer-affecting decision.

Version is `0.106.1`; Postgres, ingest, Metabase, and Operations are healthy;
root/health return 302/200; current HTTP 500, traceback, ERROR, and CRITICAL
counts are zero. Both remotes match `7f07124`.

E4 was implemented for release `0.107.0`: deployment-controlled
relationship types and authority; unresolved relationship evidence; audited
include/exclude decisions; dirty-key effective edges/support; generic candidate
create/reopen/attach projection and atomic attach/reject services; immutable
restricted source events; and going-forward Ninja `NODE_DELETED` capture. A
read-only production measurement found 4,918 currently unattached source
identities (4,842 asset observed-only, 10 client observed-only, and 66 device
pending) for the bounded initial candidate projection. It also found 228
retained deletion events, all with actor IDs but none with a stable device ID;
the nested payload contains only a message. The deployment does not backfill
those historical events and never parses message/hostname text into identity.
Future deletion events withdraw evidence only when an exact stable device ID is
supplied and in order. Python compile, Django check, migration drift, focused
Ruff, nine contract tests, and diff checks pass; no local Docker rehearsal was
run. Next: commit the scoped E4 release, push both remotes with immediate
Portainer redeploy, then verify migrations, bounded candidate/no-op behavior,
aggregate relationship/event/RLS invariants, health, and current error counts.

The first `0.107.0` deployment applied migration 0110, then 0111 rolled back
because the relationship-type seed left initially deferred entity-class foreign
keys pending before ownership DDL. No E4 data or consumer cutover occurred.
Corrective `0.107.1` forces those constraints immediately after the seed and
adds an explicit E4 regression assertion. Next: validate, commit, push both
remotes with immediate redeploy, and complete the planned aggregate checks.
