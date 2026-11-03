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

The source-record evaluator now uses independently supported client evidence for
record attribution and name-scoped candidates. The patch evidence and coverage
grids, dashboard patching counts, and affected-Computer issue rows require an
effective Computer owner before using stored client fields.
The issue queue also hides stale device-client labels and includes unresolved
device issues in its unassigned-client filter; its shared item relation and
client counts no longer treat an unresolved device finding's stored client as
authoritative. Issue detail rows and identity/Hudu Computer links also require
effective ownership before displaying client context or a client-scoped link;
the finding review page applies the same rule to client and Computer links.
Source-record issue selection and display use independent source attribution
instead of potentially inherited clients on older finding rows; organization
records use their current supported group mapping. Client scoreboard counts and
attention rows exclude source-record findings whose stored client is stale.
Dashboard issue rollups mask stale Computer clients, and software detail omits
device and client-attributed source-record findings whose clients are not
currently supported; unassigned source-record findings remain visible. Dashboard source-record
rollups use current independent attribution rather than old finding clients.
Device-scoped software decisions now lock the selected owner, and scoped
installation checks lock an effectively owned Computer through the decision
transaction. This change is unvalidated.
Global Computer search retains unresolved results without displaying or
redirecting through their stored client.
Source-record search uses the attached Computer's effective owner or, when
unattached, independently supported source attribution. The tenant-checked
evidence function is granted to the Operations app for that read; organization
records use their supported current group mapping.
Organization attribution matches the complete source identity, not just an
external ID that another namespace could reuse. When a Computer record identifies
its source group as its parent, attribution also checks that parent's namespace.
Unqualified group IDs shared by multiple current organization records remain
unknown even if only one group is mapped. This change is unvalidated.
Group-derived evidence requires one current organization record and uses its
complete source identity, including when its external ID differs from the group
key. Group-link, decision, history and client-availability invalidation also
follow that mapping. A synthetic mapped record with different group key and
external ID resolved successfully after migrations applied. The attempted
ambiguous-group fixture then violated an existing observation uniqueness
constraint. A corrected fixture subsequently confirmed the ambiguous group is
unknown and, after removing the ambiguity, the projector moves a synthetic
Computer to the supported client. The fixture was rolled back and its scratch
database dropped; dependent rows and commit-time effects were not covered.
The older local synthetic dependent-row fixture uses observation client IDs as
evidence, which the current projector deliberately no longer accepts; it cannot
validate the current contract without updating its fixture. The current schema
requires a source instance, observation, Computer and dependent installation;
the fixture must supply independent source-instance evidence for the new client.
A small synthetic-schema fixture now confirms that source-instance evidence
projects the client to a Computer entity and software installation. It uses
stub tables, so full-schema constraints and other dependent types remain untested;
the scratch database was dropped.
The projector's device update also triggers ownership invalidation. Its final
write settles the incremented revision while retaining the ownership row lock.
In the synthetic-schema fixture, a concurrent observation change waited for
that lock and dirtied ownership after the projection committed. Other input races
and full-schema transaction behavior remain unvalidated.
The source-record inventory uses independent source attribution and a separate
effective Computer owner for Computer links.
Client-candidate name evidence now requires every live same-name Computer to
have an effective owner, so an unresolved namesake cannot produce a false
single-client suggestion.
Software policy evaluation for unattached source records also uses independent
source evidence rather than the observation's potentially inherited client;
device-scoped software decisions require a live, effectively owned Computer.
Automatic group-name corroboration now fails closed when a link has multiple
matching current organization observations, instead of choosing one arbitrarily.
An operator mapping is evidence only when its decision is at least as recent as
the current link history, preventing an older decision from proving a later move.
New mapping decisions use wall-clock timestamps to compare correctly with link
history created later in the same transaction; older ambiguous decisions fail
closed and may require reconfirmation. Supersession timestamps use the same clock
so repeated decisions in one transaction remain chronologically consistent.
The migration rejects an unexpected prior decision-function definition rather
than silently omitting that timestamp change.
Client availability changes also invalidate Computers whose independent evidence
comes from a source instance or group link, including a restored client that is
absent from the observation's stored client field.
Ownership invalidation now queues attached source records for reassessment;
source, group, decision, name and client-availability changes also queue affected
unattached records. Attached records' bounded identity neighbors are queued both
when ownership becomes dirty and when projection settles, so an early unknown
assessment is revisited; unattached records affected by source mapping changes
also queue their bounded identity neighbors. Requeued affected records advance
their input version so prior assessments are not mistaken for current evidence.
Duplicate source-record cases delegate to a Computer-owned finding only when
that Computer has an effective owner. If their common Computer's ownership is
unresolved, the case remains unknown and an existing finding is preserved.
The source-record detail page labels assessments with an older target version
or a pending queue item as pending reassessment, and reports failed queue items
as failed instead of displaying the previous result as current;
the Hudu reference producer also requeues assessments with an older target version.
Unattached observations are queued
on attribution changes even when their stream excludes the group from its material
hash. Unrelated material-hash changes no longer dirty ownership; platform changes
do, because legacy accepted-record decisions use platform in their keys. A synthetic attached record was queued by direct ownership
invalidation after migrations 0392–0403 applied in a schema-only scratch database;
the fixture was rolled back and the scratch database dropped. The later neighbor
and settle requeue changes passed a small synthetic PostgreSQL fixture: an
invalidation advanced the attached record and queued a name neighbor; projection
to unknown advanced the record again. That fixture was rolled back and its
scratch database dropped, so its deferred commit-time generation update was not
exercised. Other trigger paths remain unvalidated and may increase
lock duration; review impact in rehearsal.
Changing an OS-to-Computer relationship now also invalidates the other Computers
sharing that OS, so creating or removing a shared relationship cannot leave a
previously projected owner authoritative.
The full identity resolver now scopes observations by independent source-client
evidence. Shared-source collection defers its inline identity match until the
observation is stored and the resolver can assess group-link provenance.
Inline matching for client-scoped sources checks and holds the live source
instance and client rows through a tenant-checked function granted to ingest;
collection lock duration requires rehearsal review.
Collection group-link hints are now limited to the actual source instance and
must agree on a single live client; provenance remains the projector's responsibility.
Collection uses a live instance's client when no configured client was supplied;
when one was supplied, it must match the live instance and client. An assigned
but unavailable instance client does not fall back to a group hint.
Unmatched Computer promotion and identity reassessment/preview likewise use
independent source-client evidence, preventing a stale observation client from
creating a Computer or selecting a client-scoped identity match.
Reassessment apply reruns the reviewed match and fences the candidate owner
before attaching; changed or unresolved results return to review. A focused
unit test confirmed a changed match does not attach; database concurrency and
successful attachment remain unvalidated.
Candidate queries now include matching Computers from other clients, and name
matching locks their captured owners before filtering or choosing a tier. This
closes the identified pre-lock filtering gap for returned candidates; concurrent
new candidates and the changed SQL paths still need focused validation. Python
syntax compilation passed; no database concurrency test has run for this change.
Name-candidate locking still requires end-to-end database validation.
SQL review confirms the migration revokes public execution of its internal
invalidation and reassessment functions; runtime privilege behavior remains
subject to database validation.
Scoped matching now locks every returned candidate's captured owner, including
candidates currently belonging to another client, before acting on the result.
The dirty reconciliation drain excludes soft-deleted Computers, preventing a
leftover dirty row for a deleted Computer from aborting every resolver cycle;
deleting or restoring a Computer invalidates its prior projection. A projector
batch also skips a Computer deleted after the batch selected it.
Duplicate-record admin finding writes and recovery now fence their captured
Computer owners in one evaluator batch and preserve episodes whose ownership
cannot be established; existing normalized and legacy subjects are recognized.
Refreshing a scoped human ownership choice replaces the saved evidence for the
selected observations, so a later return to an older client is assessed as a
new contradiction rather than silently accepted by an obsolete snapshot.
The behavior of these latest changes, independent-evidence SQL and invalidation
triggers remains unvalidated. The default Compose project was not running; its attempted
Postgres startup could not bind port 5433 because the existing
`ninja-dashboard-dev` project already uses it. The newly created stopped
container and empty volume were removed.
The existing local Postgres was then used for a schema-only scratch migration:
0392–0396 applied, but 0397 stopped at the findings writer guard because the
scratch migration ran as the local database owner rather than the migration role.
That scratch database was dropped. A fresh schema-only scratch database retained
the original ownership and grants; migrations 0392–0403 then applied successfully
as the migration role. The scratch database was dropped. This validates migration
order and DDL application for that version, not populated-data behavior or client
isolation. After the timestamp and decision-function changes, a fresh schema-only
scratch database again applied 0392–0403 successfully as the migration role;
the ingest role could call the two source-evidence helpers with empty inputs.
That scratch database was also dropped. A fresh schema-only scratch then applied
0392–0403 with the later source-identity changes; one synthetic explicit mapping
resolved both its organization and a parent-qualified Computer record. The
fixture was rolled back and the scratch database dropped. Projector moves,
negative evidence cases, and populated-data behavior remain unvalidated.
Python syntax parsing passed for the changed core resolver, evaluator,
source-observation, source-record, Operations view and migration files.
Continue the client-scoped reader audit and validate the critical migration and
isolation paths before completion. The migration is draft and requires a
separately authorized deployment rehearsal.
The current migrations 0392–0403 applied successfully to a disposable local
schema on the latest check; it completed before the user's request to stop the
local check. The user requested production validation instead; clarify whether
that authorizes a read-only check or applying migrations before any live change.
A read-only production schema query returned `0400_association_refreshes_computer_values`
as the latest recorded Django migration; 0401–0403 have not been applied by that
sequence. No production migration was run.
The running Operations container does not contain migrations 0401–0403, and
the local versions have uncommitted changes. Production cannot apply these
versions until the reviewed code is made available there through an authorized
deployment or another explicitly authorized method.
The user authorized preparation for production. The worktree also contains
other plans' changes, including shared files, so a PLAN-045 commit must isolate
its changes without including unrelated work. Commit and production push need
separate approval. Migration 0401–0403 startup effects, populated-data behavior,
and lock/workload impact remain review items before deployment.
`git diff --check` passed for the tracked working-tree changes before this
checkpoint update; untracked files are outside that check.

Resumed at user request from local checkpoint commit `2af7fb1b`; Git status and
diffs have been reconciled. The implementation is incomplete and must not be
pushed or deployed. Continue the remaining protections and validation below.

Current work: client-scoped Computer detail, lifecycle, patch, exemption and
merge paths check effective ownership; affected writes hold an ownership lock.
Client workspace and directory rollups, client naming, software user-risk and
tech checklists, and patching summaries partly filter by effective owner. Input invalidation covers client
availability, OS edges, companion-stream configuration and source-instance
changes. Unresolved ownership and new contradictions enter the existing review
queue without a stale client; legacy accepted records are shown for a new scoped
decision. A tenant-checked, narrowly granted function supplies ownership
decisions to ingest, whose local role lacks direct table reads. Synthetic
PostgreSQL checks pass, including two-session input versus write/projector locks
and decision-reader privileges; a focused finding check passed in the ingest container.
A schema-only scratch database successfully applied Operations migrations
0392–0403 in order, then was dropped. A Django system check against the current
Operations code passed. These checks do not cover all client readers or behavior
on a populated migrated schema. Next: finish remaining client-scoped readers,
writes and derived consumers; validate their SQL and end-to-end recovery.

Latest continuation: global Computer and client-directory displays now avoid
showing a stale client, and notifications recheck the selected owner, including
digest rows. Source-record attribution, software-policy inputs, device status
overrides and readiness signals use effective ownership; software inventory
mapping excludes unresolved Computers. Inventory now locks and rechecks the
captured owner during its write transaction and rolls back a stale-map batch for
retry; notification delivery locks captured owners and finding rows through each
attempt. Synthetic PostgreSQL and mocked notification checks pass without sending. These locks can delay source
updates during database or network work; throughput and waits remain unmeasured
and require an authorized rehearsal. Next: audit resolver/name caches, evaluator
finding reconciliation and remaining readers before claiming fail-closed behavior.

The evaluator currently uses stored clients for lifecycle and requirement
decisions. Its full requirement-state replacement and finding reconciliation
also mean that simply skipping unresolved Computers can erase verdicts or clear
episodes. Evaluation commits in batches and refreshes its snapshot between
phases, so ownership must be rechecked and fenced in each writing transaction.
Protect both evaluation and reconciliation together. The
user requested pausing the goal after the next commit; commit approval remains
separate under repository instructions.

Software queue refreshes now keep an unmapped Computer in the existing
retry/failure path even when its source-record refresh succeeds. A mocked mixed
batch passed in the ingest container; no database or external service was used.
This does not automatically requeue a request after its retry limit is exhausted.
Lifecycle transition and in-use-confirmation writes now recheck and hold the
captured ownership lock in device order; evaluator device-finding upserts also
recheck inside their write batch. Requirement evaluation excludes unresolved
Computers; replacement and reconciliation use only locked Computers whose
captured evidence revision remains current, preserving other verdicts and
episodes. A synthetic PostgreSQL check verified the actual revision-lock query,
and focused mocked checks passed. Lifecycle and generic device-finding clearance
now locks only Computers whose finding client matches their effective owner;
a synthetic PostgreSQL check verified unresolved owners are excluded. Other
lifecycle and identity-finding writers and readers still need fencing and audit.

Identity duplicate, collision, label and two-machine findings now use locked
resolved Computers; group clearance retains a finding if any recorded member
is not locked. Ownership-conflict findings stay unscoped while unresolved and
clear only for locked owners. A small PostgreSQL fixture verified grouped
clearance; an existing focused conflict check passed. This identity pass locks
all resolved Computers for its transaction, so its wait impact also requires
an authorized rehearsal. Resolver matching still needs end-to-end validation.

Automatic proven-split merges now plan only with locked resolved owners and
recheck both Computers before each merge. A survivor dirtied by one merge is
deferred until projection before another merge; focused mocked checks passed.
The merge pass takes the same fleet-wide ownership locks and needs rehearsal.
Merge-candidate and identity-conflict projections now use a locked owner set;
they retain groups with unresolved or malformed members rather than marking
them merged or resolved. The immediate identity-conflict writer also rechecks
candidate ownership. A synthetic PostgreSQL check covered the candidate-member
closure guard. Scoped matching now uses fresh targeted name and history queries,
defers unresolved candidates before promotion, and locks selected owners;
read-only previews report deferral as review. Small mocked and PostgreSQL
checks passed. Source-record identity assessment keeps existing review open
while ownership defers a match. Query cost and full resolver recovery remain
unmeasured; the earlier cached lookup was intentionally used for performance.
Resolver data-quality findings now use locked resolved owners, and shared-serial
clearance preserves findings with an unresolved recorded member. The synthetic
PostgreSQL grouped-clearance check passed for both member representations.

Client inventory counts and learned domains now exclude unresolved Computers;
source-record and held-software displays show a client only when ownership is
resolved. A small PostgreSQL fixture verified learned-domain isolation.

Source collection previously copied an associated Computer's client into its
observation, which can turn old ownership into circular evidence. The fallback
has been removed for new collection. Existing observation upserts preserve a
prior client on null inputs, and group links may already reflect the fallback;
the provenance-aware treatment of existing evidence is still unresolved. See
ADR-0052. Automatic mapping backfill labels some pre-existing links automatic
without independent evidence, so that label alone is not a safe provenance
test. Next: specify and enforce which source-instance and mapping inputs can
establish a client, including invalidation for mapping/alias changes. This is a
release blocker, not an authorized data repair.

New collection records whether its client came from a source instance, a
source-group link, or was unknown; it does not treat a group-link label as
independent proof. The invalidation trigger detects attribution changes even
when the material hash does not. Focused synthetic and PostgreSQL checks passed.
The projector does not yet consume this attribution or resolve legacy evidence.
The draft invalidation now also covers source-instance client changes, source
group link and mapping-decision changes, and observation group identity changes;
a small PostgreSQL fixture exercised the first three. A schema-only scratch
database reapplied Operations migrations 0392–0403 successfully and was dropped.
Alias/name provenance and the projector's independent-evidence rules still
require implementation.

Migration 0402 now contains an unwired, private evidence reader for explicit
source-instance clients and operator-confirmed group links with corroborating
current association history. It rejects unknown, unreviewed, stale-link and
uncorroborated automatic cases; an earlier small PostgreSQL fixture checked
those cases and tenant isolation. Source-link history changes also invalidate
the affected owner. The draft now adds automatic name corroboration and wires
the reader into projection, identity findings and operator-decision snapshots;
these latest changes are not yet validated. Existing fixture assumptions need
updating, and production impact remains unknown. Do not deploy this draft.

Windows servicing now locks and rechecks client and evidence revision before
writing; its state cleanup and finding closure cover only locked Computers. A
small PostgreSQL fixture verified state cleanup preserves an unlocked Computer.
This full-scope batch can hold many ownership locks; production waits remain
unmeasured and require an authorized rehearsal. Other scoped derived writers
still require audit.

Patch evaluation now captures and locks resolved patch-eligible owners before
device and client aggregate work; its incremental digest includes client and
ownership revision. Client backlog clearance is held when any online Computer
has unresolved or uncaptured ownership. A synthetic PostgreSQL fixture verified
the actual owner-scope SQL excludes a dirty Computer. Aggregate coverage and
closure still need broader end-to-end validation, and this fleet-wide lock set
also needs an authorized rehearsal for operational impact.

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
