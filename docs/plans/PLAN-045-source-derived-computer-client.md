# PLAN-045 — Source-derived Computer client

## Goal and scope

Derive a Computer's current client from current source records. Reconcile after
relevant source changes and during each complete resolver cycle. One supported
client projects to the Computer; conflicting or missing evidence is explicitly
unresolved. Preserve explicit human decisions and flag later contradictions.
Do not silently use an old automatic association as present evidence.

## Confirmed constraints

- ADR-0012 requires the shared projector to be the sole source-derived writer;
  do not call the operator-only `move_computer_to_client` from the resolver. That
  function records an operator action and moves multiple scoped dependents.
- `devices.client_id` is a required foreign key. Entities, OS installations,
  findings, software and other scoped rows also carry client values. Unknown
  and conflicting ownership cannot safely be represented by leaving an old
  stored client authoritative; their security and presentation semantics need
  an explicit schema contract and migration.
- Existing source-group move code implements a special case, not a general
  recalculation. Identity attachments and duplicate Computers are separate work;
  client reconciliation alone does not merge JFA-549's two Computers.
- Do not infer that a compatibility history entry proves an operator decision.
  Review existing explicit decision sources and preserve their scope/evidence.

## Proposed implementation for review

1. Specify durable derived ownership states (one supported client, conflict,
   no current evidence, and explicit operator decision with contradiction).
   Decide how unresolved ownership is represented without exposing a stale
   client's data across tenant/client boundaries. Audit every current reader,
   permission policy and dependent scoped row before selecting nullable columns,
   a separate projection, or another compatible representation.
2. Create a reviewed schema migration and a shared, tenant-scoped projector
   which updates all dependent ownership consistently, preserves audit history,
   and fails closed for conflicts and protected human decisions. Do not reuse a
   procedure that incorrectly attributes automatic changes to an operator.
3. Enqueue affected Computers on source/client/association changes and run a
   complete reconciliation during every full resolver cycle. Ensure changes
   during a cycle are not lost; retry failures without partial projections.
4. Validate with small synthetic PostgreSQL cases: unanimous different client,
   agreement, multiple clients, no active evidence, unknown-client record,
   operator decision and contradiction, concurrent evidence changes, scoped
   dependents, and idempotence. Check normal read paths and migration ordering.
5. Independently review a production preview and authorize any one-time data
   operation or deployment as required. Automatic reconciliation at service
   startup and pending migrations must be included in any deployment approval.

## Read-only production assessment, 2026-11-02

Grouping active non-org observations attached to non-deleted Computers by
their Operations-assigned source client: 3 Computers have one different known
client, no unknown-client records, valid destinations and no current
`client_conflict_accepted` decision; 25 have records naming multiple clients;
6,264 have one known client matching the stored client. Among this population,
none have only unknown clients. Another 78 non-deleted Computers have no active
non-org records. These counts are an initial scope estimate, not an exact move
set: other explicit decisions, source admissibility, stale observations,
concurrent changes and dependent ownership have not been assessed. These
figures do not count duplicate-Computer merges.

## Checkpoint

User requested a pause after the next commit. This is an incomplete local
checkpoint and must not be pushed or deployed. Resume only on request; first
reconcile Git status and diffs, then complete the remaining protections and
validation below. Commit hash is available from Git after this checkpoint.

2026-11-03: Migrations 0401–0403 and resolver integration are in progress.
0402 projects evidence and dependent client copies under the ownership-row lock;
ambiguous legacy actions are held for review, and explicit choices retain a
snapshot for contradiction detection. 0403 records choices in operator actions
and queues source-group changes rather than calling the operator move. A full
resolver sweep plus bounded dirty drain propagates failures. Initial client
Computer, software and Issues reads use the effective owner; other readers,
notifications, writes and materialized-view consumers still require audit and
enforcement. The local synthetic PostgreSQL scaffold passed resolved move,
conflict, explicit choice, subsequent contradiction, transaction, grants and
reverse checks; it is not a full migrated schema. Two focused resolver-cycle
unit checks pass. All migrations and runtime changes remain unreleasable until
the outstanding protections, input invalidation and concurrency/full-chain
validation are complete. Next: finish client-facing and derived consumers,
address concurrent input and relationship changes, then validate on a suitable
full-schema scratch database without heavy processing.

2026-11-03: Continuing with the projector. Historical `computer.move_client`
actions can result from a source-group move as well as a direct Computer
decision; the action alone cannot authorize a protected client. Implementation
must retain ambiguous legacy decisions for review and must not silently move
past them. The projector will lock the per-Computer revision row while reading
evidence and publishing dependent changes; observation and decision triggers
invalidate that row in the input transaction.

2026-11-03: Migration 0401 now defines a tenant-scoped ownership state with
dirty and projected revisions and invalidation triggers for observation,
operator-decision and roaming-record changes. It does not backfill existing
Computers: missing rows must be treated as unresolved. A minimal local scratch
PostgreSQL fixture passed insertion, two-device reattachment, decision and
roaming invalidation, rollback, tenant filtering, a runtime update-grant check,
and reverse SQL; the scratch database was dropped. These checks used synthetic schema scaffolding,
not the full 0400 migration chain. This foundation alone does not protect
client reads and must not be deployed alone. Next: implement and test the
shared projector, complete input coverage and reader enforcement; verify the
full migration chain and concurrency before deployment review.

2026-11-03: Added a pure comparison for a verified, applicable explicit
client decision against current evidence. It preserves the selected client,
reports distinct contradictory clients, and retains unknown evidence without
calling it a contradiction. Five standard-library unit tests and compilation
pass. This comparison neither determines decision applicability nor changes
runtime ownership; legacy accepted keys are not treated as client decisions.
The local database records Operations 0391, while the repository contains
0400; catalog observations must be checked against the later migrations before
use. Ruff and pytest are unavailable in the checked local environments.
Next: specify and implement database-enforced evidence invalidation and reader
isolation, then integrate this contract into the actual projector.

2026-11-03 continuation: Started the writer and consumer audit; confirmed that
two client-bearing presence materialized views can retain stale client IDs
after a Computer transition. A later refresh alone leaves a potentially unsafe
interval. Writer, decision, dependent and local schema findings and outstanding
inventory are in [the audit](../records/PLAN-045-ownership-consumer-audit.md).
Local schema metadata and policies were read without changing data. The audit is
not complete; no migration or runtime ownership change has been implemented.
Next: trace the remaining readers and privileges and design a concurrency fence
and fail-closed transition that covers materialized reads before implementation.

2026-11-03 fresh-session audit: Git status and tracked diffs were inspected;
independent PLAN-044 and other existing changes remain untouched. No ownership
migration, projector, resolver wiring, or client-scope protection was found.
The following additional implementation constraints were verified in code:

- `client_conflict_accepted` stores evidence keys, including `record:<platform>|<entity_key>`
  and `serial:<device_id>`, not an explicit target client or a snapshot of its
  evidence. The finding suppresses matching keys; a changed client on the same
  record can retain the same key. A projector must not treat this as an
  unqualified perpetual client choice.
- The operator move updates the Computer, its entity, linked OS entities and
  installations, device findings, software installations and decisions,
  Windows servicing and name collisions. The source-group move also calls this
  operator procedure. Migration must address that existing writer and audit
  shared OS relationships and decision scope before projecting changes.
- Association updates lock the source subject and source link, not the target
  Computer; locking only a Computer in a projector does not fence concurrent
  attachment. The source-group move also updates observation client values.
  All relevant writers need a common fencing/dirty protocol.
- Client filtering is distributed in direct SQL and ORM paths; the generic
  `client_scoped_query` helper has no in-tree callers. Several software queries
  use a null decision client as a broad match, so clearing that column alone
  can widen decision reach. Resolver naming maintenance catches exceptions;
  copying that pattern would conceal projection failures.

Validation this session: Python compilation and plan-registry validation pass.
Neither workstation Python nor the running ingest and Operations containers
has pytest installed, so the seven classifier tests were not rerun. The local
development containers are running; no local database changes were made.
Next: finish the consumer/decision and writer audit, design a fail-closed
transition with an enforceable concurrency fence, then implement and exercise
the migration and projector with synthetic PostgreSQL fixtures. The migration
and all requested runtime protections remain incomplete.

2026-11-03: User explicitly approved adding and testing schema migrations for
the source-derived ownership projection and unresolved states. Production data
changes, commit, push and deployment remain separate. Current Git status was
reconciled and independent PLAN-044 work preserved.

The evidence-only classifier is implemented in
`ingest/identity/computer_client_ownership.py`; 7 synthetic agreement, conflict
and unknown-evidence cases pass, along with focused Ruff and Python compilation.
It is not wired into a writer or resolver and makes no runtime change. The
projector, database migrations, concurrent-change fencing, scoped reads and
human-decision enforcement remain unimplemented.

Schema audit: `entities.ck_entities_scope_owner` requires a client when scope is
client and forbids one for tenant scope, so simply clearing the old client or
marking the entity tenant-owned would change the ownership model. Devices, OS
installations, software installations and name collisions also require clients.
Existing software-decision queries interpret `client_id IS NULL` as broad scope;
blindly nulling those rows can change decisions' reach. `client_scoped_query`
filters on a returned `client_id`, and many existing consumers read stored
client columns directly. A new projection view alone cannot enforce isolation.
Forced tenant RLS does not by itself implement client-scoped application filters.

Next: complete the scoped-reader/decision audit and specify an enforceable
transition that distinguishes unresolved client-owned entities from tenant
ownership, preserves decision scope and makes stale client copies non-authoritative.
Then implement the migration and shared projector, wire source changes and the
full resolver cycle, and validate real PostgreSQL cases before claiming completion.
No production mutation, migration, commit or deployment occurred.

2026-11-03: User requested the proper architecture-level fix and validation.
The narrower unanimous-only slice is insufficient for this request because its
old client remains visible and authoritative when evidence is unresolved.
Proposed contract and acceptance tests are in
`operations/docs/decisions/0052-source-derived-computer-ownership.md` (status
proposed). Live schema inspection confirms `devices`, `operating_system_installations`,
`software_installations_current` and `computer_name_collisions` require clients;
`entities` and findings allow null. Relevant tables use forced tenant RLS, while
client scoping also occurs in application/query filters. This is a cross-service
schema/security change, not a UI-only fix. A fresh read-only aggregate on
2026-11-03 found 3 unanimous different-client candidates, none with a recorded
accepted conflict or prior `computer.move_client` operator action; this is not a
full audit of human decisions or a repair authorization.

Next: finish the consumer, decision-provenance and concurrency audit and select a
compatible migration/rollout. Schema migration preparation and local testing are
approved. Do not assert the narrower model below as the final architecture.

### Earlier narrowed checkpoint (superseded by proper-fix request)

User clarified the immediate fix: use the existing ownership model and update
the Computer when all current records agree, following the current resolver's
rules. Do not expand this slice into nullable ownership or a new unresolved-state
schema. Preserve explicit human decisions and leave mixed or unknown evidence for
review. The full resolver cycle must reassess even when no new record was resolved.

The existing `move_computer_to_client` changes all scoped dependents but records
the actor as `operator` and is exposed to `operations_app`; calling it for an
automatic resolver action would falsify provenance. ADR-0012 assigns source-derived
writes to a shared projector, not the resolver. Implement and validate a projector
with truthful automatic provenance and equivalent dependent updates, and wire it
into the full resolver; first verify role privileges, locking and decision guards.
On 2026-11-03, read-only production privilege checks confirmed `ninja_ingest`
cannot update `entities`, `software_installations_current`, `software_decisions`,
or `computer_name_collisions`, and cannot execute `move_computer_to_client`.
Therefore the approved existing-model slice requires a database contract change.
Proposed migration: add a narrowly granted security-definer projection function
that takes a tenant and Computer, locks and rechecks all current source clients
and applicable human decisions, records a system-attributed action, and updates
the Computer and its scoped dependents atomically only when unanimous. Wire a
bounded projector into each full resolver cycle, propagating failures. Review
source-change races, actor decision provenance, and all affected dependents before
finalizing the SQL. No runtime, schema, production data or deployment changed.
Next: obtain explicit schema-change authorization, implement the reviewed function
and projector, and validate synthetic database cases. Commit and push remain separate.
