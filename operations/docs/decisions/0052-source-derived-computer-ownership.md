# 0052 — Source-derived Computer ownership

Status: Proposed for PLAN-045; local implementation incomplete and not releasable
Date: 2026-11-03

## Problem

The Computer's stored client and multiple dependent client copies can outlive
the current source evidence that justified them. JFA-549's attached records now
name another client, yet the older Computer remains in its prior client. An
issue warns of the divergence but does not reconcile it. Current client IDs are
also used as filters; stale values must not silently serve as authority.

## Proposed contract

Client ownership is a machine-level derived result of current, admissible source
records and applicable explicit operator decisions. The shared projector is its
sole source-derived writer (ADR-0012); source collection, the resolver and the UI
only record evidence or decisions and request projection. A Computer remains a
learned grouping, and source associations retain their separate authority and
history (ADR-0049/0050).

For a Computer with no applicable operator decision:

- All applicable current records have one known client: `resolved` to that client.
- At least two known clients disagree: `conflict`, with no effective client.
- No applicable current records, or an applicable record has an unknown client:
  `unknown`, with no effective client. A known-client disagreement remains a
  conflict even if another record is unknown.

A scoped human decision records what was decided, by whom, why, and against
which evidence. Later contradictory evidence must surface for review; it must
not silently replace that decision or be hidden by it. Legacy compatibility
history is not itself proof of a human decision. The precise precedence and
expiry of existing operator decisions must be audited before migration.

`effective client` is the authority for current client-scoped reads, writes,
and ownership-dependent calculations. An old stored client may be retained as
historical or compatibility data but cannot authorize or imply current client
ownership for an unresolved Computer. Unknown is not tenant ownership: it does
not turn a client-owned machine into an unscoped or MSP-owned entity.

## Enforcement and transition requirements

- A schema-backed, tenant-scoped result must distinguish resolved, conflict,
  unknown and decision-protected conditions. It must not rely on a nullable
  client alone to encode why the result is unresolved.
- Apply source, mapping, association and decision changes through a reliable
  dirty queue and a full resolver-cycle sweep. Fence concurrent updates so a
  completed projection cannot certify stale evidence; retry failures visibly.
- For a resolved client, update all ownership-dependent copies atomically, with
  truthful system attribution. Do not use the operator-attributed move function
  for automatic projection. Decide how shared OS relationships and existing
  operator-owned software decisions behave before implementing moves.
- Audit client-scoped ORM, SQL, UI, exports, queues and API consumers; unresolved
  Computers must not leak into a previous client's results. A new view alone is
  insufficient while existing consumers read stored `client_id` directly.
- Respect forced tenant RLS and grant the minimum privileges. Existing RLS is
  tenant-based; client filtering is also application/query logic, so both require
  validation. Read models must have write privileges revoked as required by the
  Operations instructions.
- Backfill must be bounded, restartable, and separately approved for production.
  Keep existing decision and change history. Client reconciliation does not by
  itself merge duplicate Computers or change source associations.

## Validation and acceptance

Use synthetic PostgreSQL records to prove unanimous agreement and change,
conflict, absent and unknown evidence, stale evidence, human decision and
contradiction, tenant isolation, client-filter isolation, dependent ownership,
concurrent source/decision change, retry/idempotence, and full-cycle recovery.
Verify migration order, rollback/forward recovery, privilege boundaries, runtime
packaging, and current UI/API/export consumers. Use the smallest local fixtures;
production data, rebuilds and deployment each remain separately controlled.

## Unresolved implementation choices

The local draft uses a separate ownership state and invalidation revisions;
the projector, operator-choice snapshot and initial reader changes are in
progress. The representation is not enforced across all consumers, and
source admissibility, complete invalidation, compatibility rollout and
concurrency behavior still need review and validation. The user authorized
preparation and local testing of schema migrations on 2026-11-03; production
execution and deployment remain separate.
