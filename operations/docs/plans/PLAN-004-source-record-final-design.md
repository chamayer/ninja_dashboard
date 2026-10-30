# PLAN-004 — Final managed-record evaluation design

Status: Revision 8 accepted by the user after independent review, 2026-10-29.
Case combining (PLAN-033) and source-record notifications (PLAN-034) are deferred.
Acceptance approves this design only; implementation, migrations and production
operations each still need separate authorization.
The [handoff](PLAN-004-source-record-review.md) owns the current checkpoint;
[ADR-0049](../decisions/0049-managed-record-evaluation-before-identity.md) records
the amended design decisions. Earlier supporting drafts are inventories, not
additional commitments where they conflict with this revision. The
[review summary](../records/PLAN-004-design-reconciliation-2026-10-29.md) explains
the scope reductions and validation limits.

## 1. Decisions and scope

Every received source record is a managed evaluation subject immediately, regardless
of Computer identity, class resolution or client mapping. Its record, source claims,
findings, decisions, history, comparison participation and applicable actions are
addressable from intake. Association with a real-world entity enriches that subject;
it does not admit it to management or replace it with another identity.

The managed subject is a native mechanism reference, `source_record`, with a durable
UUID and source natural key. Multi-record work uses a native `source_record_case`.
Neither is a canonical entity/Computer nor a new findings ledger. This is the same
architectural distinction that permits a source binding or Job to have findings.
ADR-0012 continues to govern evidence, entity anchors and projector-owned state.
ADR-0044 remains proposed independent taxonomy work; source evaluation does not wait
for it. All tenant/restricted-record protections apply from the first lookup.

The complete behavior covers independent correctness and purpose; weak/strong
evidence comparison; identity/attribution; explicitly expected representation;
qualified maintenance; explained corrective work; per-claim use; verified closure
and reappearance. Existing code is a compatibility map, not the scope authority.

## 2. Durable subjects, associations and simple cases

These are logical contracts; numeric migration names are implementation work.

| Relation | Minimum contract |
| --- | --- |
| `source_record_subjects` | Durable UUID and tenant/source-instance natural key, key version, admitted time, current observation pointer, record role/presence, input version and association version. Composite tenant FKs, unique natural identity. Malformed received items get a separate unique source-run/item identity and explicit intake-error outcome. Names, class, client and Computer do not define identity |
| Existing `entity_source_links` / history | Add tenant-scoped source-subject reference and association version. One current confirmed entity per source subject. Retain method, evidence and audit history; project observation `device_id` from this authority |
| `source_record_tenant_state` | One protected row per tenant with transactional `input_generation BIGINT`. Every relevant input mutation advances it in the same transaction. This coarse counter replaces lookup-bucket generations; it is not a notification cutoff |
| `source_record_lookup_keys` | Indexed tenant, owner UUID/kind, compatible role, key family, normalization version, normalized value and evidence reference. One protected writer; restrictions apply to keys as to raw claims. No bucket table, per-key counters or pairwise cross-product |
| `source_record_cases` | UUID, tenant, family, correction dimension, compatible role, one immutable shared-key family/value/normalization version, state, version and closure audit. Partial uniqueness for one open case per scope. Optional duplicate-of case, decision reason, relevant evidence fingerprint and validity flag; a valid duplicate disposition also reserves that scope against automatic recreation |
| `source_record_case_members` | Tenant, case and source-subject UUID, evidence role/reason and joined/released provenance. Unique active case/member; each member directly qualifies under the case's shared key. Composite tenant FKs |
| `source_record_assessment_current` | Target UUID/kind, rule/dimension, rule/config revision, target/member versions, captured tenant input generation, result/evidence/missing facts, assessed/expiry/next-due times. Unique target/rule/dimension. Protected derived writer |
| Existing registered assessment queue / outbox | Coalesced target dirty revision, lease/retry/next-due state under Jobs ownership. Admission and enqueue are atomic. Completion must not erase a newer enqueue |
| Existing `source_action_requests` | Exact native target and selected members, expected rule/config, input and decision revisions, idempotency key, tenant FKs and allowlisted operation. Revalidate before external action |

Rules are code-defined with validated configuration values. Persist a rule/config
revision for invalidation and explanation; no immutable JSON policy interpreter or
separate policy-version service. Reuse PLAN-019/ADR-0045 history rather than adding
another first-observation ledger. There are no notification continuity, activation,
cutoff-assessment or work-claim tables in this release.

### 2.1 Confirmed-association authority and writer handoff

`entity_source_links` plus its history is the sole confirmed-association authority.
`entity_observation_current.device_id` becomes its compatibility projection.
Only `operations.set_source_association(...)` changes the link, history and projected
value, checking expected association version and tenant permissions. (Amendment
R4-1: the caller takes no tenant guard; the generation row serializes commits.) It updates lookup entries, advances the tenant
input generation and queues affected evaluation atomically. No additional authority.

| Current writer | Handoff |
| --- | --- |
| Intake (`source_observations.py`): policy match via `resolve_device_fast`, and connector-supplied `resolved_device_id` for non-identity sources | Takes the §7.2 tenant guard for the whole batch, then admits the subject. Then, in the same transaction, calls the procedure only when the approved automatic policy (§5) qualifies; a failed or ambiguous match leaves the subject admitted and unassociated. Connector-supplied references become typed reference evidence and associate only under that same policy |
| Resolver fast-path/match/promotion (`identity/resolver.py`, `_attach_observation`) | Calls the procedure with method, evidence fingerprint and expected version; promotion first creates the entity |
| Merge/split/link move (`merge_computers`, `split_computer_merge`, `split_computer_records`, `move_computer_links`) | Bodies call the procedure per affected subject (associate, repoint or clear), inside the action's own transaction; resulting versions are written to the action audit |
| `move_computer_to_client` (0340) | Not an association writer: it changes Computer ownership. It must advance the tenant input generation for the ownership-context change (§7.1) and enqueue dependents |
| Candidate attach/promote (`entity_candidate_decisions`) | Calls the procedure; the existing "attached elsewhere" refusal becomes the expected-version check |
| `move_client_source_group_v1` (repoints a source-group record's link to another client entity) | Calls the procedure for the group record. Group-to-client mapping is a confirmed association of the group record; record-level Computer associations are untouched |
| `sync_entity_source_links_from_observations()` | Retired as a writer at cutover; replaced by a read-only parity check that reports any divergence as a finding, never repairs it silently |
| `seed_observation_current` command | Must not write `device_id`; reads the projection from links. Disabled for production until converted |
| Observation upsert (`ingest/observations.py`, current-row `device_id = COALESCE(EXCLUDED.device_id, current)`) | The actual intake writer behind `source_observations.py`. Stops writing `device_id`; the projection comes only from the procedure |
| Source deletion events (`ingest/source_events.py`, link `missing_since`/`source_deleted`) | Presence update, not an association change. Route through a protected presence-only entrypoint that advances the tenant input generation; never direct link DML |
| `ingest/derived.py` caller of the sync function | Remove the call when the sync writer retires; it is a shadow path (§8) |


Revoke direct runtime link/history and observation `device_id` writes; grant only
the protected procedures. A consistency trigger rejects a projected attachment that
differs from its link. Inventory all real writers against the release commit.
During the authorized cutover, drain affected writers/resolver, review every
link/observation divergence, backfill subject references, switch the procedures,
projection and grants together, verify parity and resume compatible writers.
Unknown writers or unexplained divergence block cutover, not a guessed repair.

Use tenant validation and forced RLS from the first lookup; safe views and exports
must not reveal restricted members through names, counts, errors or links. Revoke
runtime DML on derived tables and read views. Canonical entities, source evidence,
operator decisions and projected values remain separate responsibilities.

### 2.2 One-time reassessment of existing associations

Preview -> review -> apply; never clear all associations first. Preserve canonical
IDs, explicit attachments/separations, source-group mappings, history and decisions.
Preview creates no Computers or association changes. Classify outcomes as same,
changed, ambiguous, unmatched or newly matched with old/proposed targets, evidence,
versions and reasons. Review changed/ambiguous/unmatched dispositions explicitly;
reviewed policy may cover unchanged and justified newly matched rows.

Apply only still-current reviewed dispositions through the protected procedure.
Changed inputs return that row to review. Keep rollback mappings and verify parity,
operator state and intended association outcomes. Coordinate PLAN-015 rather than
running competing repairs. This semantic operation needs separate authorization.

Use an explicitly approved maintenance window covering final application, authority
switch, verification and abort/recovery. Estimate its duration by rehearsal; no
arbitrary 30-second promise and no unbounded outage. Agree a stop/abort point and
compatible checkpoint before starting. Do not keep intake stopped for fleet-wide
rule evaluation. Resume intake after cutover checks, then process queued work.
Preview legacy finding/notification consequences too: existing notification behavior
is retained, not a guarantee that reassessment cannot produce a legitimate alert.
There is no E3R/E4 notification baseline, staged successor or activation sweep.

## 3. Intake, evidence and resolution lifecycle

**Amendment R4-1 (user decision 2026-10-30, supersedes the guard clause below).**
Intake does not take the tenant guard. A database trigger on
`entity_observation_current` performs admission in the observation-write
transaction: it upserts the subject by natural key, sets the current observation
pointer, advances the subject input version on a decision-relevant change, replaces
its lookup keys and enqueues the subject plus its old and new neighbors. A deferred
constraint trigger on `source_record_subjects` advances the tenant input generation
once per transaction at commit, so the generation row is locked only for the commit
itself. Intake code needs no admission call and cannot skip it. A trigger failure
rolls back the observation write, as the paragraph below requires. Chosen as the
fastest option for incoming data: R2's exclusive writers (evaluator sessions of
about 24 minutes) would otherwise stall collection.

After acquiring the §7.2 tenant guard, in the observation-write
transaction: upsert the source-subject anchor by its exact
natural key; write the observation/current pointer; increment decision-relevant
generation; enqueue independent assessment work. Roll back the whole transaction
if managed admission/outbox fails. Identity resolver completion is not a dependency.
Both new and already linked records follow this path. An empty/unknown hostname
cannot silently exclude a record from management or independent evaluation.
Run optional automatic association inside an inner savepoint after admission. A
policy/association failure rolls back that part, retains the prior confirmed link
if any, records the failed assessment and enqueues retry without losing admission.
Never swallow an admission, tenant, input-generation or outbox integrity failure:
those roll back and visibly fail/retry the item under the source-run contract.

Record-role mapping has an explicit unclassified fallback. Run structural/reference
and source-state checks on it; record role-dependent rules as unknown with the
missing-role explanation. Do not guess a Computer class. A malformed input lacking
a usable natural key is accounted for by an intake-error subject keyed to source
run/item ordinal, with safe diagnostics and source-run failure accounting; it is
not discarded or merged by payload similarity. Collection-scope configuration
(what a collector requests) is source configuration, not admission. A record that is
received despite an exclusion policy is admitted with that policy as context and
evaluated against it; it is never silently dropped. Excluded-at-source counts are
reported separately from received/admitted counts.

Reappearance of the same natural identity reuses the subject UUID. Source withdrawal
sets presence and retains the anchor/history; it never automatically deletes a
canonical entity. If a source demonstrably reuses its identifier for a different
object, retain the source-subject continuity while versioning its represented-entity
association and showing the discontinuity. Do not silently claim lifelong hardware
identity from a stable session/agent ID.

Possible identities are comparison results and case members; only a confirmed
association is written, through the §2.1 procedure. Repointing, merging or splitting
canonical entities updates association versions and invalidates dependent
assessments. Original source attribution remains unchanged. Record-level
findings retain subject/episode UUIDs. Genuine entity-level findings stay with the
entity; source subjects participate as evidence. The shared relationship contract
links independently correctable concerns without multiplying the action count.

First-observed data follows ADR-0045/PLAN-019, not a second independent source of
truth on the new subject. `admitted_at` means admission to this management mechanism,
not source creation or first hardware sighting. Reuse established values/basis; backfilled
history is a labeled lower bound, never source creation or installation time. Reuse
its significant-change mechanism where implemented; do not add daily presence or
expand its accepted detailed-history retention. This plan does not require retaining
all raw payloads/intervals indefinitely.

## 4. Rule-input and execution matrix

Each code-defined rule declares role applicability, exact required facts, optional
corroboration, freshness/completeness, target scope, use restrictions and closure.
Every applicable rule is scheduled independently. Unknown applies to a missing
input of that rule, not the whole managed item. Freshness is policy and evidence
specific; inherited source collection time never becomes device activity time.

| Evaluation | Inputs | Identity/ownership dependency | Defined output and work |
| --- | --- | --- | --- |
| Structural/identifier quality | Raw/normalized claim, schema/rejection policy | None | Valid, invalid or unknown per field; invalidity can raise exact-field correction and restrict only the affected use |
| Source presence/status/time quality | Snapshot contract, reported status and typed timestamps | None | Separate present/withdrawn, reported connected/offline and contact-known/unknown; flag established contradictions or invalid required data |
| Reference correctness | Typed target namespace, reference and permitted target evidence | None for structural checks; resolution only for a rule proving target existence | Invalid target/reference, conflict or precise unknown; link-repair work is separate from archive |
| Record purpose | Role, authored required/permitted/disallowed/retention/exception policy and actual observations | Only the particular contextual policy clause that requires it | Supported purpose, established mismatch or precise unknown; optional is not unwanted |
| Candidate comparison | Comparable roles and any useful names/MACs/IDs/references/history | None; authorized cross-client comparison is possible without asserting ownership | Possible/supported-same/supported-different/unresolved explanations; concrete ambiguity work as specified below |
| Source attribution | Original group/site assertion and mapping/ownership evidence | Group evaluation independent; entity-ownership claim needs that association | Unmapped, conflicting or settled; mapping one record cannot map the group |
| Replacement/staleness | Defined proof or valid configured source-role age predicate/exceptions | Supported represented-object identity only for replacement; age can evaluate unassigned records | Immediate proven-replacement review, qualified stale review or unknown; no implicit source action |
| Entity service/documentation requirement | Explicit applicable entity/OS/client/profile policy and trustworthy presence | Only facts that specific requirement actually needs | Met, missing, conflicting or unknown from the rule; pending identity cannot prevent all other record evaluation |
| Existing security/other independent finding | The owning rule's real input contract | Only its actual inputs | Continue to evaluate supported risks, including real unwanted installations; purpose/identity uncertainty is not a blanket suppressor |

Rule result values are `supported`, `contradicted`, `unknown`, `not_applicable`;
absence of a current required assessment is `not_assessed` in read diagnostics.
Map these onto the existing condition response/coverage engine; add no second
operator status or general Readiness category. Operator Open/Paused/Resolved remains
separate. Rule failure is explicit; an unavailable consumer cannot publish a clean
verdict or clear established work. Collection problems are independent where proven;
correlation alone does not cover unrelated risks.

### Condition families and configuration gaps

These are initial concern contracts, not permission to migrate or
emit them now. Use distinct non-alertable source-record type keys for native targets; keep legacy
keys and targets unchanged. Register new entries through
PLAN-003 with explicit native subject/participant and action membership.

| Concern | Type contract | Subject and count scope |
| --- | --- | --- |
| Qualified unresolved identity | New `source_record_identity_review` for unassigned decisions; existing Computer identity case remains the entity action owner | Source record/case for unresolved association; canonical entity case for merge/split work. Critical; shared evidence does not duplicate the same decision |
| Possible duplicate entries | New `source_record_duplicate_review` with source/role boundary | Record case per duplicate-review correction scope; retain current agent/Hudu severity where meaning matches |
| Invalid serial/MAC | New `source_record_identifier_invalid`, with serial/MAC field dimension | Record target with field dimension; preserve current severity without retargeting old Computer episodes |
| Other established field/reference errors | New `source_record_data_incorrect`, rule/field dimension | Record/case where one correction resolves it; Medium unless a reviewed impact policy overrides. Do not duplicate the placeholder or Hudu link type for the same repair |
| Consequential purpose mismatch/question | New `source_record_purpose_review` | Record or same-action case; Medium; explicit unknown policy alone is not a per-record issue |
| Proven replacement or qualified stale record | New `source_record_cleanup`, reason replacement/stale with evidence | Exact record target; one cleanup decision even if both reasons apply. Medium by default; source action remains separate authorization |
| Hudu archive/link/configured integration work | Native source corrections use non-alertable `source_record_reference_review` or cleanup; existing legacy types retain their targets and owners | Exact record for source repairs; actual connection/configuration scope for proven integration work. Do not infer archival purpose from relay failure alone |
| Source-group/ownership work | Existing mapping and `computer_client_conflict` families | Native source/group or canonical owner as appropriate; exact scope/action manifest reconciles entity/admin duplicates |
| Missing explicitly required representation | Existing applicable requirement type for unchanged service meaning; new `required_representation_missing` only for a registered non-platform expectation | The known entity/client/source-instance scope owning the expectation; never a fictional absent source record. Medium default; existing security-service severity remains unchanged |
| Required rule/role policy absent or invalid | New `source_record_policy_incomplete` | One actual source-instance/role/configuration decision, affected record subjects as impact; Medium. Optional disabled rules or deliberate unknown optional inputs do not create a configuration issue |

Rule applicability/mandatory configuration is itself versioned data. Required
configuration failures and worker failures are visible at their real administrative
scope while independent record evaluation continues. Do not hide all purpose/age
unknowns behind successful collection or manufacture thousands of identical tasks.
New condition names require registry uniqueness checks before implementation;
resolve a naming collision before activating the type, without retargeting legacy work.

## 5. Evidence and action rules selected for the first policy

Discovery unions current/former/normalized names, usable MACs, serial/VM identifiers,
typed references and recorded continuity. Domain, site/group, hardware/context and
timing explain/refine those comparisons; do not create every pair sharing a domain.
Names of arbitrary documentation assets do not become endpoint hostnames by default.
Scope ID equality to the owning source namespace; allow comparable claims across
instances/platforms. Cross-platform corroboration is normally legitimate.

Implement lookup keys as indexed tenant/role-qualified source/identifier/name/MAC/
reference entries maintained on dirty inputs, with exact normalized equality rules.
Large weak-name buckets remain complete counted/paged candidate sets; do not persist
their full pairwise cross-product. Materialize only selected comparisons and
rule-qualified evidence edges. The UI can enumerate the full bucket without claiming
that every pair is an issue or silently truncating candidate selection.

Record independent evidence lineage, specificity, age, opposing and missing facts.
A normalized name and a link inferred from that same name count as one origin.
Do not use an arbitrary sum/score, required serial, or transitive weak-match group
as proof of identity. Investigations can show potentially relevant evidence side by side under
§6.1, showing the actual edges, missing facts and contradictions rather than
asserting that connected members represent one Computer.
Same name or MAC alone can initiate investigation without establishing a defect.

Automatic association, proposed first-version rules:

- Existing confirmed source association supplies continuity, but new conflicting
  or discontinuity evidence triggers reassessment; it is not unconditional proof.
- One unique compatible tenant-local entity with a usable non-roaming serial/VM
  match and independent supporting evidence may qualify when no identifier,
  concurrent-record, ownership or operator-separation conflict remains.
- Name-based association is allowed within one established client when the current
  authoritative comparable record-name/variant policy yields one unique compatible
  entity, the name is permitted by the data-backed identity-value/name policy, and
  conflict/separation checks pass. No serial is mandatory. Ambiguous normalized,
  truncated or historical-name results remain unresolved. Exact prior heuristics
  are compared in tests; none is grandfathered merely because it exists.
- Unknown source-group mapping is distinct from conflicting mapped ownership.
  A qualified unique corroborated hardware association may proceed under ADR-0048
  without mapping that group. Never derive group ownership from a likely identity.
- Several eligible candidates, conflicting identifiers, simultaneous same-source
  reporting without adequate explanation, clone/reuse uncertainty or a relevant
  operator separation prevent automatic association. Recency orders the workspace;
  it cannot break an unresolved identity tie. Merging entities needs its own
  stronger reviewed action contract; it is never a side effect of weak discovery.

Create an identity issue when a role requires an identity decision and the evidence
leaves competing eligible possibilities or an established contradiction; a weak
similarity bucket alone is not an issue. Create record-correction work for an
established rule discrepancy or a consequential purpose decision with explicit
scope. Unknown optional data creates no issue. Unclassified role can raise one
source-role configuration task with affected records as impact rather than a
mandatory manual approval per record.

Purpose configuration defaults to `unknown`, never required/permitted/disallowed.
No missing requirement alone establishes unwanted software. A positive operational,
documentation or retention policy can establish justified presence. Confirmed
disallowed purpose produces record/service correction work, without erasing the
evidence that the installation is real. Exceptions record exact scope, reason,
actor and expiry or changed-evidence trigger.

Replacement requires supported same represented object and equivalent role, plus
trusted explicit supersession or adequate actual succession chronology, and no
unresolved contrary evidence or distinct continuing purpose. The measured three
ScreenConnect pairs do not establish it. Once proven, review is immediate. Stale
age requires an explicitly enabled role policy with valid time semantics, threshold,
collection adequacy and expected offline/retention exceptions. No configured threshold
means unknown; this is the selected safe behavior, not an invented numeric default.
No new automatic deletion, archiving, installation removal or collection is enabled.

Severity: qualified unresolved identity is Critical, independent of confidence.
Preserve current per-type severity for unchanged meaning; proposed new field/purpose
correction and maintenance conditions default Medium unless explicit policy identifies
greater impact. A new age condition needs its explicit enabled policy/severity.
Changing a legacy type's meaning/severity requires a separately reviewed legacy change and
notification continuity check, not a display rename. Hints/unknown optional data have no issue severity.

## 6. Work identity, cases and guarded actions

Source-record findings use native `source_record` UUIDs; investigations use native
`source_record_case` UUIDs. Register exact subject/participant/action combinations
in PLAN-003. Validate tenant, target existence, natural reference agreement and
current permissions. Never fabricate a Computer or use arbitrary JSON as a target.
An episode key uses durable target, rule family and correction dimension, excluding
mutable name/client/Computer labels. Existing resolution/history semantics remain.

### 6.1 One case per qualified shared-key question

Use one open case per tenant/family/dimension/role/shared-key tuple, enforced by a
partial unique index. One serialized assessment/publisher worker initially updates
membership and findings under the exclusive tenant guard. Concurrent operator
changes still use the same guard and constraints; uniqueness is not a stale-input
check. No separate anchor-claim table, combine procedure, redirects or repointing.

A record can appear in name N1 and MAC M cases without making them the same
question. Joining through M does not adopt any other key. If D has name N2 and
shares M, it joins M; qualified N2 work gets its own case/finding. Every qualified
case/dimension has a finding regardless of overlapping members. Similarity alone
is not a defect, and membership never proves transitive physical identity.

Show related cases side by side with provenance, opposing/missing facts and exact
membership. Page large sets; do not materialize every pair or publish a truncated
aggregate as complete. No fixed anchor/member count thresholds. Case combine and
split mechanisms are deferred to [PLAN-033](PLAN-033-source-record-case-combining.md).

Member withdrawal re-evaluates the case. Closure requires its own rule's verified
closure test; closing X cannot close overlapping Z. History and old UUID links
remain available. A genuinely new occurrence after resolution creates a linked
episode under existing lifecycle rules.

An operator may close a duplicate with an audited `duplicate_of` reference, reason
and current evidence scope. It means duplicate work, never verified correction.
Reject self/cyclic/cross-tenant references. Retain a valid duplicate disposition's
scope reservation so the evaluator does not immediately recreate it. Relevant
source/decision changes or target closure requeue both cases and recheck that
coverage; if no longer valid, clear the reservation and reopen/create actionable
work with history. Do not silently follow redirects or inherit target resolution.
Counts distinguish open investigations, duplicate dispositions and record impact;
shared members alone never deduplicate independent questions. No new Covers matcher.

Actions name exact selected records and operations, reuse the existing allowlist,
permissions and idempotent source-action worker, and revalidate current evidence,
rule/config revision and decisions under §7.2 before submission. External calls
hold no database locks. Existing workers still recheck freshness immediately before
execution. No new automatic deletion, merge, archive or installation removal.

## 7. Scheduling, freshness and closure

Eligibility is per claim/intended use: invalid serial does not invalidate useful
connectivity, unknown attribution grants no ownership, and an issue decision cannot
make an invalid claim true. Shared projectors remain the only writers of selected
source-derived entity values. Missing data yields explicit unknown, never clean.

### 7.1 Coarse generation and neighbor scheduling

Every relevant input writer atomically advances `source_record_tenant_state` with
its source, lookup-key, membership-relevant, association, ownership, restriction,
completeness, operator-decision or rule/config change. A record's own version alone
cannot detect another record entering or leaving its comparison set. Use one
transactional tenant generation instead of per-key buckets/counters. Derived
assessment touches do not advance it; operator case decisions that affect rules do.
The counter row adds brief tenant-wide serialization at mutation commit; accept
that simpler tradeoff initially and measure it before release.

Queue changed records and former/current neighbors using indexed old/new lookup
keys in the input transaction. Preserve old keys long enough to discover departures.
The durable queue retains dirty revisions arriving during evaluation; acknowledgments
only complete the revision actually processed. On comparison-key arrival/departure or scope/restriction changes, also enqueue a
coalesced tenant comparison refresh as the conservative repair for reciprocal
concurrent changes missed by neighbor queries. Do the same when other dependents
cannot be enumerated safely. Use the same
registered queue, processed in bounded pages. No dedicated bucket fan-out service.
Reciprocal concurrent arrivals, removals and restriction changes must not lose work.
One worker owns assessment/publication work initially; Jobs lease recovery resumes
failed work without requiring identity resolution.

Evaluation reads inputs, target/member versions, tenant generation and rule/config
revision in one read-only consistent snapshot, then ends that transaction. Publication
acquires the exclusive tenant guard in a new READ COMMITTED transaction and reads
the generation again after lock acquisition. Any changed generation/revision
invalidates the result; discard/requeue it. While this guard is held, shared input
writers cannot commit a change between validation and publication. No generation
value from an unlocked pre-read authorizes a write. This protects candidate-universe
changes without per-key advisory locks. Tenant-wide invalidation is deliberately
conservative; measure retries under continuous ingest before release.

Actions and rule consumers also refuse stale assessments; enqueuing a newer result
does not authorize acting on the older one. Time predicates and exception expiry use
existing next-due scheduling even when facts do not otherwise change. Changed inputs
cannot close findings until their closure rule is evaluated with current facts.

### 7.2 Minimal locking and bounded transactions

**Amendment R4-1 (user decision 2026-10-30).** Input writers (the intake trigger,
`set_source_association` and the presence entrypoint) take no tenant guard. They
serialize only on the tenant generation row, which the deferred subject trigger
updates at commit. Publication takes the exclusive tenant guard, then
`SELECT ... FOR SHARE` on the generation row, and holds both until it commits. An
input commit therefore cannot land between validation and publication; it waits for
one bounded publication batch. The worker reads its inputs after acquiring both
locks, in the same short transaction, so the generation it publishes against is
current by construction and continuous ingest cannot starve publication. Batches are
small, with statement and lock timeouts. Lock timeouts requeue the batch rather than
fail it. Graph, finding, case and operator-action writers keep exclusive mode as below.

**Amendment R4-2 (user decision 2026-10-30): load measurement waived.** The
representative concurrent-ingest measurement in the last paragraph of this section
is waived for this release. The workstation rule forbids load runs, and no other
environment was authorized. Instead, watch ingest run timings, the queue depth and
the age of the oldest dirty revision after release. If intake slows or the queue
does not drain, stop and review measured alternatives, as below.

Retain only two tenant-guard categories, using PLAN-003's one migration-owned key:
input/admission/association-only mutations take shared mode; finding, assessment,
participant, rule/relationship, case publication and operator action mutations take
exclusive mode. If an association transaction also resolves a finding (candidate
attach, for example), select exclusive mode at its outer boundary. No upgrades.
Protected entrypoints verify the actual held mode; runtime roles cannot bypass input
procedures, graph procedures or the transactional generation advancement. Nested
helpers are private. No per-key lock plans, hashes, namespaces or ticket coordinator.

Acquire tenant guard before domain row locks; retain PLAN-003's protected row order.
Multi-tenant operations order tenant guards consistently. Register every actual
input/graph writer at implementation review; this small write-set distinction
replaces the large per-writer mode matrix, not the association-writer inventory.

Use configured database statement/lock timeouts, an overall transaction deadline,
small independently complete intake/publication batches and bounded retries with
backoff. Record effective limits before release; a timeout aborts visibly and retains
retry work. Batch unchanged-assessment touches as well as changed results. Do not
hold a tenant guard over an ingest run, collection, notification or other network
call. Oversized atomic actions fail explicitly rather than silently losing atomicity.

Before deployment, exercise concurrent ingest, comparison publication and operator
updates on representative local synthetic data. Measure throughput, lock/transaction
waits, retry age and queue drain; verify intake continues and work progresses within
the reviewed limits. There are no invented millisecond/100-outcomes-per-second
contracts. If the coarse counter or single worker cannot sustain the workload, stop
and review measured alternatives before rollout; do not wait for production complaints
or silently restore the removed coordination machinery.

## 8. Rule-by-rule reconciliation and amendments

| Existing logic | Final design disposition and reason |
| --- | --- |
| Resolver identity-signal allowlist and client-scoped promotion | Keep class-appropriate canonical promotion; separate managed intake and record evaluation so all roles participate before promotion |
| Source identity shortcut | Continuity evidence with reassessment on material contradiction/discontinuity; no perpetual hardware-identity guarantee |
| Serial/VM match, rejection and roaming guards | Qualified strong evidence with independent corroboration for new unassigned matching; preserve field validity guards, explicitly handle reuse/clones/source errors |
| Exact/loose/15-character/former-name matching | Keep these as discovery evidence. First automatic policy requires reviewed scoped uniqueness/conflict checks; ambiguity never resolved by recency |
| `hostname_mac` requiring a name candidate | Keep its justified action semantics; add MAC-only/different-name discovery so evidence is not discarded |
| Domain differences | Supporting normalized context, not universal separation; DNS/NetBIOS differences are not defects by themselves |
| Most-recent-activity candidate selection | Replace as an identity tie-break; use for investigation order only. Proposed ADR-0032 amendment required |
| Same-source-live and conflicting-ID blockers | Retain conservative automatic-action refusal; replace universal two-machine assertion with interpreted evidence and specific unresolved alternatives |
| Operator `identity_separate`/excluded-record values | Honor exact scope while current; migrate legacy platform/key ambiguity explicitly; reconsider only on relevant changed evidence through review |
| Duplicate-platform evaluator joined to Computers, keyed by platform/type/layout | Reuse the source-duplication concern, add managed record/case targets and proper source namespaces/role equivalence. Independent comparison crosses sources; duplicate cleanup does not follow cross-platform corroboration |
| Placeholder findings on canonical serial/attached recent MACs | Assess exact source claims without requiring association; keep the existing Computer findings and their history unchanged (no retargeting, §9.1) and report valid unaffected claims separately |
| Entity/admin unmatched-group overlap | Reconcile exact source/group/action identity with PLAN-003. Preserve admin-only or independently correctable work; close obsolete duplicates only by manifest with reason |
| Computer identity versus source hygiene (ADR-0043) | Separate corrective work and share evidence/context. Weak comparison does not merge Computer identities or independent issues |
| Client conflict (ADR-0040) | Keep ownership decision scope; record-level identity association cannot assign the entire source group |
| Hudu stale/divergent/unintegrated findings | Keep exact archive/link/integration decision meanings where justified. Remove client mapping as record-evaluation prerequisite. Unresolved relay links alone do not establish obsolete purpose; vendor-support hints alone do not prove a broken configured integration |
| Whole-Computer lifecycle/stale data and required-agent findings | Keep independently justified domains, audit exact evidence inputs, remove only blanket identity-dependent gating of unrelated record rules; do not repurpose these as per-record cleanup |
| Existing complete-snapshot and current-policy guards | Keep their protection against false absence/closure; bind to exact target scope/input generation, not just any recent successful collection |
| Hudu-only explicit source-action worker | Keep credential separation and exact target checking; extend only allowlisted capabilities after authorization. No ScreenConnect deletion is implied |
| Existing source-subject natural keys/history | Reuse stable identity semantics; introduce durable native subject UUID without claiming source identity is physical identity. ADR-0045 remains history authority |
| Generic projection shadow paths | Preserve current authority until explicit audited conversion, as above; no architecture promotion hidden inside this change |
| `entity_observation_current.device_id` as attachment authority, derived links sync | Invert: links become the single confirmed-association authority, `device_id` a protected projection (§2.1). Justified because operator decisions already write links directly, so two authorities exist today |
| Notification fingerprint from `condition_key`, `device_id` rule/suppression match | Keep the mechanism; do not retarget/re-key legacy findings in this release. New native types are UI-only; future notification continuity is PLAN-034 (§9.1) |

This is a local code/design reconciliation, not a claim that current production
policy rows or all external consumers were audited. The approved stopped-discovery
boundary remains. All consumers found during implementation must enter the same
manifest before activation; an unknown consumer blocks cutover, not record admission
in the old deployed system.

## 9. Three-stage implementation and rollout

This design authorizes no execution. Each stage needs approved implementation,
relevant checks and the repository's separate release/operation approvals.

| Stage | Scope and release boundary |
| --- | --- |
| A: managed records and independent rules | Add durable subjects, indexed lookup keys, coarse generation, registered queue and native assessments/findings. New native types default not alertable. Include the necessary PLAN-003 native target validators/readers/graph guards before emitting findings; that common-store cutover retains its own compatibility and approval requirements |
| B: association authority and one-time reassessment | Convert all inventoried writers to the one procedure and protected projection; preview/review reassessment. Use the approved maintenance window for incompatible writer/schema/grant handoff and final reviewed application, verify parity, then resume intake and incremental evaluation. Preserve source and decision history and a compatible abort/recovery checkpoint |
| C: simple cases and workspace | Add one-key cases, qualified memberships/findings, paged related-case workspace, audited duplicate references and safe counts/actions. No combines or notification activation |

Compatible additive schema/code may deploy normally only after verifying old/new
writers, nullability/defaults and startup migration behavior remain compatible.
An additive label alone is not evidence of compatibility. Incompatible writer/grant
or PLAN-003 storage changes use a coordinated drain/version boundary. Stage A must
not enable incompatible writers before its guards/validators exist. Include all new
runtime files in images and reconcile migrations, models and entrypoints.

No E3R preactivation artifact, shadow-successor reader, E4 cutoff/sweep, five-minute
dispatch transition or catch-up machinery. No fleet reassessment/conversion runs at
startup. Keep reviewed manifests for association dispositions and exact ownership
of existing versus new finding producers, not notification conversion maps.

### 9.1 Existing notifications stay; new native findings are UI-only

Use distinct native source-record/case type keys with `alertable=false`, enforced
by the existing type/response registry and dispatcher selection. Do not retarget an
existing alertable type or reinterpret its Computer subject as a source record.
Existing legacy finding IDs, fingerprints, targets, suppressions, cooldown and delivery
history remain owned by their current producers and dispatcher. This release does
not retire those paths or redefine reserve/send/record behavior.

At implementation, record an exact rule/target/correction ownership matrix: where
legacy work already represents the same correction, the native assessment links to
that finding instead of emitting a second task. New uncovered corrections may create
UI-only native findings. An ambiguous ownership mapping blocks that rule's new finding
activation, not managed intake or independent assessment. Never guess a Computer or
silently close legacy findings to make counts agree. Simple-case questions that are
independent retain their findings even when their members overlap (§6.1).

No baseline/release ledger, activation cutoff, exact-set notification sweep,
fingerprint alias graph, route-principal framework or special no-route catch-up
state is introduced. Existing no-route and delivery-retry behavior stays unchanged;
this is not a promise of exactly-once delivery or absence of a legacy backlog burst.

Restricted records remain protected in UI, exports and any reused payload path.
Do not add new member context to existing notification payloads. If any adapter must
send new context, default to minimal non-sensitive text and a permission-checked UI
link; a route called MSP-only is not sufficient authorization to disclose metadata.
Existing route security findings, if discovered, need separate scoped correction.

[PLAN-034](PLAN-034-source-record-notifications.md) owns future source-record alerts:
authorized MSP destinations, baseline/eligibility and material changes, delayed
assessment, suppressions, visibility, no-route policy and conversion continuity if
needed. Do not enable the new types merely by toggling alertability or use first-opened
time as an already-approved eligibility policy. Case combining is separately
[PLAN-033](PLAN-033-source-record-case-combining.md); neither plan blocks this UI-only
release, and neither has implementation approval.

Rollback uses the reviewed compatible stage checkpoint and retains history/decisions.
Do not erase subjects, silently restore old associations, or blind-close/regenerate
findings. Destructive recovery, data rebuild and production actions require their
own explicit approval.

## 10. Acceptance and review gate

| Case | Required observable outcome |
| --- | --- |
| Resolver stopped, unassigned or malformed received record | Durable managed subject or explicit intake-error outcome; independent applicable assessments/findings remain available, with exact unknown reasons |
| Name-only, MAC-only, conflicting or ambiguous identity | Complete indexed comparisons and qualified case work without automatic arbitrary attachment, transitive identity or assumed client ownership |
| Correction, concurrent arrival/removal, restriction or association change | Tenant generation blocks stale publication/action; indexed enqueue or conservative paged refresh loses no dependent work; newer dirty revisions survive acknowledgments |
| Coarse guard under representative ingest | Bounded transactions, effective timeouts and measured queue/lock/retry behavior; intake continues and evaluation progresses. No locks across network calls |
| Association handoff and reassessment | Every writer converted; direct DML denied; parity checked; reviewed still-current dispositions only; canonical IDs, decisions and history retained; approved window/abort procedure |
| Overlapping cases and duplicate closure | One open case per key scope; every qualified independent question has a finding; duplicate reference retains history/reservation, rechecks relevant changes and never means verified correction |
| Restricted participant and native action | Tenant/RLS/permissions hold for lookup, detail, count, export and exact selected action; no hidden member disclosure or ownership escalation |
| Notification compatibility | New native types cannot notify; legacy fingerprints/state/producers remain functional; no unreviewed duplicate correction or payload expansion |
| Packaging and lifecycle | Migrations/model state/roles/entrypoints agree; runtime files included; compatible additive versus coordinated cutover is demonstrated, not assumed |

Run focused ingest/rule and PostgreSQL tenant/generation/queue/association/concurrency
tests, native-subject request/action/template/export checks, relevant Django/Ruff,
registry/link/packaging and whitespace checks during authorized implementation.
No production mutation tests or copying live payloads into fixtures. Ordinary missing
policy defaults remain unknown; preserve purpose/severity/age semantics in §§4–5.

Accepted 2026-10-29 after independent review of this contract, the ADR amendments,
PLAN-003 integration and the PLAN-033/034 deferrals. PLAN-003 owns the tenant guard
helper and common findings foundation; Stage A builds on it (handoff: ownership and
order). Load checks must keep complete input freshness, never a target-only check.
Documentation consistency is not implementation, runtime, load or deployment evidence.
Local writer inventory is based on a dirty worktree and must be rechecked against
the actual reviewed release. Production discovery remains stopped.
