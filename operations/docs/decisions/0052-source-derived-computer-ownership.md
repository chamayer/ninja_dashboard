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

## Local draft: independent evidence

An observation's stored client can have been inherited from its attached
Computer, so it cannot by itself prove that Computer's ownership. The draft
uses a live client-scoped source instance, or a current source-group mapping
whose provenance is independently supported. Operator mappings require a
current matching link history no newer than the decision; automatic mappings
require an unambiguous
current group name and a live client name or trusted alias. A missing or
unproved mapping is unknown evidence. Source-instance attribution takes
precedence when present. Input changes invalidate the affected projections.
Group-derived evidence requires one current organization record and matches
its complete source identity to the mapping. An unqualified group ID shared
by multiple current organization records is ambiguous even if only one of
those records has a mapping.
New mapping decisions use a wall-clock timestamp consistent with association
history; older decisions with ambiguous ordering require reconfirmation.
Ownership invalidation and settlement also queue affected source records and
their bounded identity neighbors, so assessments made while ownership is unknown
can be revisited. These queues execute inside the changing transaction; their
lock and workload impact must be reviewed in an authorized rehearsal.
This contract and its concurrency behavior remain subject to validation.

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

## Local draft: transaction fencing

The draft locks ownership rows in stable device order when client-scoped writes
or inventory projection rely on an owner. Inventory rolls back and reports a
retry when a staged Computer's captured client no longer matches. Notification
delivery locks the captured owners and finding rows,
rechecks the selection, and retains those locks through each delivery attempt.
This closes the check-to-send ownership window but can delay concurrent source
changes while an inventory transaction or network request holds a lock. The
delivery clients have network timeouts; these do not prove a maximum total lock
duration. Lock waits, throughput and failure/retry behavior require a separately
authorized rehearsal before deployment. Do not measure them on the workstation.

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

The collection path previously copied an associated Computer's client into an
observation when its source instance or group had no mapping. Existing current
observation upserts preserve a prior client when a later input is null, and the
fallback could also populate a group link. Those stored values are not proven
independent source-client evidence. New collection no longer applies that
fallback, but existing observations and links need a provenance-aware transition
before the projector can safely treat them as current ownership evidence. Do
not infer or rewrite historical source mappings without reviewing the available
decision and source-binding provenance.

Source-instance `client_id` is an explicit scoped input. Client source-group
links alone are not sufficient proof: they can be derived from `org`
observations populated by the former fallback. In addition, the resolver's
automatic mapping backfill records undecided pre-existing links as automatic,
including links whose attachment preceded mapping decisions. An `automatic`
mapping decision alone therefore does not establish independent evidence.
Explicit operator mappings and independently corroborated automatic mappings
need distinct, enforceable treatment; a free-text reason is not a provenance
contract. Mapping, alias and source-instance changes also need invalidation
fences if the projector reads those inputs directly.

The local draft records the client lookup basis on newly collected observations
as `source_instance`, `source_group`, or `unknown`; it invalidates ownership
when this metadata changes. The label records what collection used, not whether
a group link is independent. Legacy observations lack the label, and the
projector has not yet been changed to evaluate it. The draft remains unreleasable
until provenance, legacy handling and their invalidation rules are enforced.
The draft now invalidates affected Computers when source-instance clients,
source-group links or their mapping decisions change. Alias and client-name
changes still need fencing if automatic name corroboration is used as proof.
The draft evidence reader recognizes source-instance clients, operator-confirmed
group links backed by current association history, and automatic mappings whose
current group name independently identifies one client. It returns unknown for
uncorroborated or stale mappings. The draft projector and operator-decision
snapshots now call this reader, and source-link history changes invalidate the
affected ownership state. The latest automatic-name rules and wiring have not
been validated; the draft remains unreleasable.
