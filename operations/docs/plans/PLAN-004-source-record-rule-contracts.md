# PLAN-004 — Proposed assessment and action contracts

Status: Supporting rule contracts, 2026-10-29; not implementation approval. The
[final design](PLAN-004-source-record-final-design.md) resolves open alternatives
below and is the controlling implementation contract. This explains
the [domain design](PLAN-004-source-record-design.md). Existing implementation
is compatibility evidence, not the definition of the need. No further discovery.

## Assessment unit and output

The unit is a stable source record or an explicitly identified comparison set,
not a Computer. Every rule declares its applicable record roles, comparable claim
semantics, evidence requirements, decision outputs and correction/closure test.
Every record is admitted to managed Operations scope immediately under an
addressable identity, with findings/participants, evaluation, history and applicable
actions available before final identity resolution. The source-scoped key supplies
initial addressability; it does not assert which physical machine is represented.
The selected managed-item mapping is a durable native source-record evaluation
subject, with a separate native case for multi-record work. Source natural keys
remain unique provenance; the subject UUID survives association changes and row
recreation. This is an evaluation mechanism, not a canonical entity class.
Original assertions and operator decisions remain evidence; source-derived state
continues to have a single projector owner under ADR-0012.

Each result identifies the rule/version, stable source targets, evidence observation
times and freshness, supported/opposing/missing evidence, conclusion, consequence,
recommended action, action authority and closure test. Provenance identifies the
producer and relay lineage; confidence describes the conclusion. Neither changes
severity automatically. The result distinguishes checked-supported, contradicted,
unknown, not applicable and not assessed without creating a second UI status system.

An assessment can exist without an issue. Issues represent work requiring a
specific corrective action or consequential unresolved judgment. They are not a
count of record pairs, missing optional fields, or unperformed checks.

Schedule applicable non-identity assessments directly from admission/evidence
changes, independently of resolver success. Rules needing missing identity,
ownership or requirement context return that precise input limitation while other
rules proceed. Do not fabricate ownership or a missing-service verdict to force
completion. Incomplete identity cannot block all findings about the managed item.

## Candidate discovery

Build the union of candidates found through usable strong identifiers, normalized
and historical names, usable MACs, typed source references, and recorded continuity.
Use domains, attribution and temporal evidence to explain/refine these candidates;
do not compare every record in a shared domain or customer group to every other one.
No discovery path requires attachment, mapped client, serial or VM UUID. An operator
can also compare explicitly selected authorized records without a detector match.

Compare across source instances where claims are comparable. Scope every external
identifier to its owning source namespace before interpreting equality. Compare
records representing compatible objects: an organization name or a documentation
location is not automatically an endpoint hostname. Do not use a broad source-name
switch as a substitute for a declared record-role contract.

Candidate generation uses indexed/batched lookup keys and incremental changed-record
work. Recompute affected neighbors when evidence changes or disappears. Generic
names can produce large buckets: page/count them without silently truncating the
candidate universe, and do not automatically infer one machine from the bucket.
Broad buckets alone do not create an issue. Exact query/index design and workload
bounds must be reviewed before implementation; this proposal adds no dependency.

## Identity conclusions

| Evidence situation | Conclusion and proposed behavior |
| --- | --- |
| Shared name/variant or MAC, no established identity | Retain a possible association and its evidence; search for corroboration and contradiction. No automatic duplicate finding merely from that hint |
| A record needing identity resolution has competing eligible candidates under its reviewed role/scope policy | Raise one unresolved identity question with all candidates and evidence; do not invent a new Computer merely to avoid the ambiguity |
| One policy-qualified identity with sufficient corroboration, uniqueness, and no disqualifying conflict | Supported same identity. Automatic association may proceed only if its separate ownership/action guards pass |
| Distinct usable identifiers or source-specific evidence of different machines | Evaluate hardware change, bad source fields, reuse and chronology. Establish separation only when the evidence supports it; otherwise retain a material conflict and refuse unsupported automatic association |
| Strong evidence conflicts or has clone/reuse/roaming ambiguity | Unresolved; show both explanations. More weak signals cannot cancel the conflict |
| Insufficient evidence without a consequential identity decision | Unknown assessment; retain evidence without manufacturing an issue |

Automatic name association requires a justified reviewed rule; prior implementation
or approval alone does not justify its future behavior. A serial is not universally
mandatory. Name-based action eligibility requires the reviewed
normalization/uniqueness/scope policy, adequate conflict checks, and no applicable
operator separation. Candidate discovery remains broader than those action rules.
Never infer ownership from name equality or from the Computer selected by identity.

Do not form automatic identity groups by transitive closure of weak matches:
A shares a name with B and B shares a MAC with C does not establish A=C.
Every proposed association must have its own evidence test. The operator sees
connections and contradictions rather than an unexplained merged cluster.

## Independent record accuracy, purpose and expectation rules

Accuracy rules operate even without a comparison partner: invalid identifiers,
malformed required values, wrong typed references, incompatible lifecycle/status
claims, and contradictions established by applicable evidence contracts. An optional
missing value is unknown, not a confirmed source defect. A normalization disagreement
must identify whether the discrepancy originates in the source or our interpretation.
Unsupported semantics remain not assessed rather than silently treated as valid.

Purpose rules distinguish required, permitted, explicitly excepted and disallowed
roles from absent policy. Required and permitted services can both justify records;
not required does not mean unwanted. An explicit documented retention purpose can
justify an inactive historical record. Unknown policy creates an assessment gap,
not blanket deletion eligibility or an approval task per record. A qualified
purpose question names the operational decision it affects and the evidence needed.

Expectation rules start from explicit applicable inventory, documentation or service
requirements. Only complete enough evidence can establish a missing representation.
A source outage is an assessment limitation or its own collection problem, not proof
that every installation disappeared. Requirements are assessed additionally when
their entity/OS/service scope is established; source records need not acquire a
Computer solely to make their accuracy or purpose assessable.

## Replacement and staleness

Proven replacement requires (1) supported same underlying identity, (2) equivalent
record/installation role, (3) either explicit trustworthy supersession evidence or
adequately retained chronology establishing succession, and (4) no unresolved
contrary evidence or distinct continuing purpose. Chronology must distinguish record
creation/installation, actual activity, connection events and collection. Merely
observing one online and one offline does not establish succession or no overlap.

Once proven, cleanup review is immediate under ADR-0048. No age or new grace period
is added. This finding does not authorize software removal, source deletion, or a
canonical entity change. The measured three ScreenConnect pairs remain possible
associations with separate attribution/maintenance questions, not proven replacements.

Staleness requires a source/role policy naming the timestamp semantics, validity,
threshold, collection adequacy and expected offline/archived/retention exceptions.
The threshold is an explicit policy parameter: no unapproved numeric default.
Missing policy or valid time produces unknown, never stale. A valid recent guest
connection can establish reported connectivity without substituting for an absent
LastActivityTime. Preserve the distinction in assessment and display.

## Effect on consumers of source evidence

Assessment must affect evidence use as well as operator work. Apply eligibility
per claim and intended use, never through a single good/bad record flag. Preserve
the original evidence and explain any restriction alongside the selected value.

| Assessment result | Required consumer behavior |
| --- | --- |
| Rejected/invalid identifier | Keep the original assertion visible; exclude that identifier from identity corroboration. Other valid claims on the record remain usable |
| Possible name/MAC association | Allow discovery, ranking and explanation; association actions apply their stricter policy. Do not assert ownership or merge identities from the hint |
| Unresolved attribution | Preserve reported grouping and authorized global visibility; do not manufacture confirmed ownership or client-specific scope from a likely match |
| Unknown contact time with reported connectivity | Retain both facts. Do not derive inactivity duration, deny the connectivity assertion, or substitute collection time |
| Contradictory material claims | Preserve each source claim and the contradiction. Select effective values only under explicit attribute authority/quality policy; if no permitted selection is supported, expose unknown/conflict with last-known history distinguished |
| Purpose questioned or installation undesired | Continue to represent actual observations, including security/unauthorized-service risks. An unnecessary installation can still be real and reporting |
| Source outage or partial snapshot | Expose collection limits. Do not infer withdrawal, absence of an installation, repair, or loss of all previously established independent risks |
| Proven replacement or qualified stale record | Make the exact record eligible for maintenance review. Do not automatically retire the Computer, erase historical claims or declare requirement fulfillment/absence |
| Verified correction/withdrawal | Reproject affected effective claims under the appropriate domain rules, then reevaluate identity, attribution, lifecycle, requirements and findings that consume them |

Consumers must use the shared versioned eligibility assessment appropriate to their
decision, not independently reinterpret an Issues status. Closing, pausing or
acknowledging a finding cannot make invalid evidence valid. Conversely, an open
maintenance concern cannot invalidate every accurate claim on a record.

Avoid circular truth: raw/normalized claim validity is assessed from evidence and
source contracts, not from the effective value selected using that same claim.
Cross-source checks identify agreement/conflict; they cannot manufacture an
independent reference truth. Rule dependencies must be explicit and acyclic.

The enforcement proposal is a versioned assessment/eligibility read contract,
consumed by the shared projector and domain evaluators, with tested use-specific
eligibility rules. Evaluators never write source-derived state directly. Evidence
or decision changes dirty affected source targets and dependent entities through
the existing queue contracts; projector completion precedes evaluation of the new
effective state. No UI action directly patches selected values or requirement state.
Consumer conversion needs one reviewed authority boundary; no mixed old/new policy
silently produces conflicting identity, coverage and display conclusions.

## Work identity and action contract

Use stable source targets plus rule/action scope as work identity; exclude mutable
Computer/client attachments, displayed names, confidence and timestamps. Field
corrections name the field/reference dimension. Each independently correctable
source target remains distinguishable even when presented in one workspace.

Identity review can reference unordered stable record-pair targets and relevant
candidate identities. Preserve a case anchor when membership changes; reconcile
overlapping cases explicitly with retained history/redirects rather than constructing
new issue identity from a changing list of members. Weak-link connected components
must not become asserted machine identities or automatic action groups.

Use the selected native `source_record` / `source_record_case` subject kinds with
required durable subject UUIDs. PLAN-003's validated `subject_ref` records supporting
provenance and must agree with the native target. The reference carries a key-format version and the stable
tenant/source-instance/namespace/parent/external-ID tuple. Computer/client references
are optional validated context, not ownership inferred from the source target.
Multi-record work retains exact member references and an immutable case anchor.
Canonical serialization is versioned before hashing keys; normalize only fields
whose source contract permits it. Display labels never enter identity keys.

The proposed validator checks required fields, source-instance tenant ownership,
allowed subject/rule/action combinations, member tenant consistency, and current
record permissions before reads/actions. Missing current evidence can be resolved
through retained source history for closed-case inspection; it is not proof of
deletion or permission to expose historical restricted payloads. This is an evidence
target, not a new canonical entity, fake binding, or third findings ledger. The
structured-subject migration and writer/reader validation ship under PLAN-003's
reviewed coordinated cutover, never as an unguarded local JSON convention.

Every action declares exact targets, permission, reason/audit requirements, current
evidence and policy fingerprint, preconditions, permitted effects and closure test.
Re-read those guards at execution; stale previews require reevaluation. Use the
PLAN-003 closed action registry and protected writer direction rather than granting
general record mutation. Proposal of an action is not authorization to execute it.

| Action family | Execution boundary | Resolution evidence |
| --- | --- | --- |
| Associate, merge, split, or confirm separate | Reviewed identity guards, operator exclusions, ownership checks, and applicable authorization | Reassessed exact association/identity discrepancy, with recorded decision |
| Correct group mapping/ownership | Explicit scoped mapping decision; record association cannot map a group | Correct attribution and reassessment of affected independent concerns |
| Correct source data | Exact source target and approved source operation; where unsupported, provide a source link and verified repair instructions | Successful applicable refresh shows corrected claims |
| Correct collector/projection interpretation | Reviewed code/configuration change through its own approval path | Verified corrected interpretation of the evidence, followed by reassessment |
| Archive/delete source entry or remove installation | Separate exact operation approval and appropriate source capability | Refresh verifies source outcome; removing an entry does not prove software removal |
| Accept legitimate exception | Actor/reason, exact concern and evidence scope, expiry or change trigger | The scoped judgment is settled while unchanged; unrelated/new evidence remains eligible |

Read/review is available even when corrective execution is unavailable. Never hide
the concern simply because its owning system lacks an automated repair API.
Acknowledgment/pause does not assert correction. No automatic destructive cleanup.

## Work lifecycle and presentation

Discovery hints stay in record comparison context. Qualified unresolved questions
and established problems enter the shared Issues contract. Titles state the
question/problem; the workspace supplies the investigation, recommended outcome,
remaining specific operator judgment, alternatives, and guarded actions.

Count independent corrective work once. Several evidence records do not multiply
one action; independent repairs do not collapse just because they share a Computer.
Source attribution, likely identity and confirmed ownership are visibly distinct.
Unassigned work is visible in authorized global scope and relevant drill-throughs
without assigning a client or leaking restricted details.

Unresolved identity retains the accepted Critical severity; same-name hints and
unknown optional timestamps do not inherit it. Other domain severities require
explicit policy. Confidence, evidence freshness and execution guards remain separate
from severity and operator handling.

Reevaluate after evidence, policy and decision changes, and on time boundaries for
age rules. Partial collection or loss of measurement cannot close an established
problem. Close only the discrepancy the verified action resolves. Preserve the
episode and operator history; changed evidence/withdrawal/reappearance must not
inherit an unrelated exception or create silent duplicate work.

## Delivery and compatibility contract

1. Finalize the versioned record-role/evidence-use policies and structured target
   validator together with PLAN-003. Justify retained and changed matching rules;
   propose explicit ADR amendments for policy changes. Do not silently replace configured
   authority or introduce an arbitrary stale threshold.
2. Implement immediate managed admission, record assessment and candidate comparison
   independently of final identity resolution.
   Add meaningful contract cases for isolated records, weak signals, strong conflicts
   and temporal uncertainty. Reuse evidence storage; do not collect customer fixtures.
3. Integrate common-store subjects, episodes, actions and consumers in PLAN-003's
   protected writer/reader cutover. Generate an explicit manifest for each existing
   finding family: retain, convert in place, merge with preserved history, or close
   with a reason. Never bulk-close findings because a new detector omits a case.
4. Expose the comparison/resolution workspace and shared Issues/drill-through/export
   selection. Show supported conclusions and exact remaining judgments. Validate
   permissions, action-preview freshness and counts against the same selection.
5. Rehearse the migration and bounded anonymous comparison in the isolated test
   environment; validate actual PostgreSQL roles, constraints, concurrency, projector
   dependencies and performance before a separately approved release.

Use compatibility reads/aliases only where the reviewed migration requires them;
avoid a second permanent authority or dual interpretation of claim eligibility.
Rollback preserves source observations, operator decisions, finding/case identities
and history. Disable new action execution before any authorized rollback of its
schema/policy generation, and restore a mutually compatible reader/writer/projector
artifact. Any data backfill, production run or rollback retains separate approval.

The implementation proposal must inventory exact runtime files, schema/privilege
changes, type/policy changes, queue dependencies, packaging and migration order,
with forward/rollback checks. That inventory is technical preparation, not a request
for the user to reconstruct missing requirements.

## Acceptance and remaining approval decisions

Contract checks must cover: isolated records; absent attachment/client; name-only
and MAC-only candidates; name variants/history/domain context; generic-name buckets;
correlated relays; nontransitive weak links; contradictory strong identifiers;
clones/roaming; explicit separations; source-boundary collisions; one versus multiple
installations; retention exceptions; missing required representation; unknown times;
partial collection; record repair and reappearance; stale action previews; exact
target permissions; and count/export parity. Validate runtime-role and concurrency
behavior before implementation closeout, with no production mutations for tests.
Hold the identity resolver pending or failed and prove the same managed items
still receive applicable non-identity findings, assessments and actions. After
identity completion, retain their source history and reconcile related work
without duplicating management identity or losing prior evaluation results.

The final design fixes native targets, rule dependencies, first-policy defaults,
condition/severity mappings, case reconciliation, constraints, rollout and acceptance.
Deployment-specific purpose/age policy uses its defined unknown/configuration-gap
behavior until configured. ADR-0049 and the complete proposal await approval;
executable migrations/code and measured runtime/rehearsal results remain
implementation deliverables, not unresolved design alternatives.
