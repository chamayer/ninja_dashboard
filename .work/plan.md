# Active root implementation plan

Track: **ADR-0010 generic entity, claim, relationship, and admin completion**

**Status:** full remaining plan approved; Phase E1 validated and release pending.

## Authority and checkpoint

- The user authorized autonomous implementation, commits, both pushes, and
  their coupled Portainer deployments. Validation should remain basic and
  proportional: syntax/static checks, migration consistency, one disposable
  PostgreSQL rehearsal for schema changes, and basic deployed
  version/health/HTTP-500 checks.
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

### E1 — Generic entity and source-link kernel (`0.104.0`, active)

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

### E2 — Attribute definitions and delta claims

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

## Active E1 affected files

- `operations/apps/core/models.py`, `operations/apps/core/admin.py`, and new
  migration `0101_generic_entity_source_link_kernel.py`.
- Focused schema test if needed, root/Operations plans, ADR-0010 status,
  `VERSION`, and `CHANGELOG.md`.

## Basic validation and deployment

- `python manage.py check`, `makemigrations --check --dry-run`, targeted Python
  compile/Ruff on changed files, and `git diff --check`.
- Apply migration 0101 once in disposable PostgreSQL 16; verify aggregate
  backfill counts, RLS/policies, uniqueness, grants, and reverse-order safety.
- Commit only E1 release files, push `origin`, immediately trigger Portainer,
  push the identical commit to the mirror, then verify `0.104.0`, migration
  application, service health, expected root status, and zero HTTP 500s.

## Current checkpoint and next action

Phase E1 is implemented as release `0.104.0`. Django checks and migration-drift
checks pass; changed Python files compile and pass focused Ruff checks. An
exact forward/backward rehearsal on disposable PostgreSQL 16 produced two
anchors, two current links, two open link-history intervals, all five forced
RLS policies, and zero writes on an immediate idempotence rerun. The known
fresh-database bootstrap dependency on the retired Agent Compliance schema at
migration 0017 remains pre-existing and outside this phase; the focused 0101
rehearsal used the deployed pre-0101 contract.

Next: commit and push `0.104.0`, immediately deploy through Portainer, verify
the migration/backfill and basic health/500 state using aggregate-only checks,
then begin E2 if deployment is healthy.
