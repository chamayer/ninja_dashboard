# PLAN-004 — Source-record assessment and resolution design

Status: Supporting domain rationale, 2026-10-29. The
[final design](PLAN-004-source-record-final-design.md) resolves the modeling,
policy defaults, condition mappings and rollout contract and takes precedence
over earlier alternatives or open questions below. The user stopped discovery and requested
design. No implementation, migrations, source changes, commit, or deployment
is authorized. [Handoff](PLAN-004-source-record-review.md),
[needs](PLAN-004-source-record-needs.md), and
[measured evidence](../records/PLAN-004-record-evidence-2026-10-29.md).

The [proposed rule/action contracts](PLAN-004-source-record-rule-contracts.md)
specify discovery, evidence decisions/use by consumers, issue eligibility,
structured source targets, actions, closure and coordinated delivery. They distinguish proposed behavior from unresolved policy
and schema decisions; no implementation approval is implied.

## Outcome and scope

Operators can find and resolve discrepancies in source records whether or not
those records have a Computer or client mapping. Each concern explains what is
known, what is uncertain, the exact records involved, and what would resolve it.
Computer identification, attribution/ownership, and requirements remain distinct
assessments sharing evidence. Association never certifies accuracy or purpose.

User clarification: every source record must enter Operations as a managed,
addressable item and participate in evaluation and findings without waiting for
identity completion. Computer identification is enrichment, not admission to
management. The design must support non-identity evaluations, finding subjects
and participants, actions and history from that initial managed identity.
Missing context may limit a particular conclusion/action, never suspend all
evaluation of the item. The final design selects durable native source-record/case
evaluation subjects, separate from canonical entities, under ADR-0012. They support
findings, participants, history and actions from intake; a display-only reference
does not satisfy the requirement.

Assess records, compare related evidence, identify the discrepancy, group work
by corrective action, then verify resolution. These are reasoning stages, not
a pipeline requiring successful attachment before subsequent assessment.
The need defines the scope; current matchers, findings, subjects, and storage do
not define it. Observations establish real problems without limiting the design
to those examples. Possible explanations remain hypotheses until supported;
no detector may assert a live duplicate installation or ingestion defect merely
because that explanation is possible.

## Justification of existing rules and proposed dispositions

Existing behavior and prior approval are evidence of the baseline, not reasons
to retain it. Judge each rule by the need it serves, supporting evidence, known
failure modes, alternatives, and the harm of a wrong decision. Proposed changes
below do not change runtime or silently amend an accepted ADR. A justified future
rule can differ from current behavior; migration compatibility is a separate task.

| Existing rule/assumption | Justification and evidence limits | Proposed disposition |
| --- | --- | --- |
| Every record must attach/be managed | The user clarified the purpose: all records must be managed/evaluable in Operations immediately, including for non-identity findings. Completing Computer identity was never intended as a gate | Keep universal admission to managed evaluation; separate it from final Computer association. Verify the target model supports all required evaluations, not merely source display |
| Client scope precedes comparison | Scope reduces false name matches and protects ownership. It also excludes observed unassigned records from useful comparisons | Remove as a comparison prerequisite; enforce tenant/record permissions and evaluate ownership separately at action time |
| Same source identity stays on its Computer | Source identity supports continuity, but retained history includes roaming identities and hardware/identifier changes | Treat as continuity evidence; permit challenge/reassessment when relevant evidence changes |
| Serial/VM equality identifies one machine | Useful strong evidence, supported by measured cross-source matches. Cloning, reuse, roaming, vendor field semantics and hardware changes qualify it | Keep as strong qualified evidence, not an unconditional equivalence or mandatory admission criterion |
| Differing usable identifiers prove different machines | Often supports separation, but a hardware change or incorrect source field can explain disagreement | Use a material conflict requiring interpretation; block unsupported automatic association without universally asserting two machines |
| Same-source simultaneous online records imply different machines | Protects against incorrect merges. Two reporting identities do not logically establish two physical machines; equivalent installations or stale assertions remain possible explanations | Keep a source-specific action guard where justified; replace the universal physical-identity conclusion with explicit unresolved alternatives |
| Names can support automatic association | ADR-0032 documents successful utility and sources lacking serials. That justifies using names, not every existing normalization, scope or ambiguity heuristic | Keep names/variants/history as evidence; justify each automatic name rule by scope, specificity, uniqueness and conflicts rather than grandfathering it |
| Choose the most recently active candidate when several remain | Produces a deterministic attachment and avoids more Computers. Recency establishes recent activity, not that the candidate is the right machine | Use recency for investigation ordering. Propose unresolved identity when ambiguity remains; this changes an accepted ADR-0032 policy and requires explicit amendment |
| Duplicate detection starts with attached Computers | Convenient aggregation; no domain reason to exclude unattached evidence | Replace the prerequisite. Require comparable roles and supported concern; neither attachment nor multiplicity establishes redundancy |
| An archived record is not current operational coverage | Appropriate when policy requires a current service. Archival may still satisfy history/retention needs | Evaluate claim use and requirement semantics; no global invalid-record flag |
| Replacement/stale age qualifies cleanup review | Replacement can establish obsolete representation; age can identify maintenance work under an appropriate source policy. Neither proves deletion is always correct | Retain only these justified meanings: immediate replacement review, qualified age review, exact action authorization and verified outcome. Add independent accuracy/purpose assessments |
| Preserve operator decisions and history | Necessary to explain actions, avoid undoing intentional separations on refresh, and distinguish changed evidence from repeated evidence | Retain scoped, reviewable decisions and relevant history; do not grant permanent immunity or invent indefinite retention requirements |
| Tenant/restriction enforcement and one writer per derived state | Prevents cross-tenant disclosure and contradictory independently written conclusions | Retain the required protections. Justify/review the actual mechanism and privileges rather than assuming current enforcement is adequate |

Evidence basis: local matcher/resolver/evaluator/source-action paths, ADR-0032,
ADR-0048, and the linked measured record. Historical rationale is not a new accuracy
measurement. This is a bounded domain reconciliation, not an exhaustive audit of
all finding types, configured policies, SQL functions or external consumers.
Unverified behavior stays explicitly unverified; no further production discovery.

## Complete assessment and resolution contract

| Responsibility | Required result |
| --- | --- |
| Establish representation | Admit every record as a managed/evaluable item; distinguish its source identity from the machine, installation, session, VM object, or documentation it represents. The latter identity can remain unresolved |
| Assess each record independently | Check applicable identifiers, attributes, references, attribution, reported activity and lifecycle even when no comparable record exists |
| Discover and compare related evidence | Include strong and weak indicators across authorized sources, instances, current records and history; attachment is optional context |
| Establish purpose | Explain a supported operational, documentation or retention purpose, or the particular uncertainty; accuracy and recent activity alone do not justify existence |
| Reconcile expectations | Check explicitly applicable service/documentation requirements independently; existing correct records do not prove completeness |
| Investigate discrepancies | Test competing explanations and distinguish observation, hypothesis, supported conclusion and authorized action |
| Recommend and resolve | Identify the exact target and correction, assemble evidence, automate only policy-supported authorized decisions, and route the remaining specific judgment |
| Verify and maintain | Verify each correction, preserve history/exceptions, and reassess after relevant evidence, policy or time changes |

For each applicable question, distinguish supported, contradicted, unknown and
not assessed. An unchecked question must never appear as a clean result. No
detected contradiction is not proof of accuracy or purpose, and optional missing
data is not a defect. Assessment completeness is diagnostic information, not a
new issue/readiness category or a mandatory manual approval for every record.

## Evidence discovery and judgment

Candidate discovery is deliberately broader than action eligibility. It must not
require a serial, VM UUID, Computer attachment, or mapped client. A common name
alone can bring records into comparison; it does not by itself establish a defect.

| Indicator | Contribution and limitation |
| --- | --- |
| Same/similar name | Weak association; include normalized, truncated and separator variants, former names, and name specificity. A generic name is weaker than a distinctive one |
| Shared MAC | Supporting association, including differing-name cases; distinguish physical, shared, virtual, cloned and roaming adapters |
| Domain agreement | Supporting context after accounting for DNS/NetBIOS semantics; disagreement alone does not separate machines |
| Source group/site attribution | Ownership/context evidence, not physical identity; preserve contradictory attribution independently |
| Source/integration reference | Compare typed, instance-scoped targets; strength depends on the reference's correctness and whether it was inferred by name |
| Activity sequence | May support continuity/re-enrollment when comparable timestamps establish sequence; current online/offline contrast is insufficient |
| Historical continuity | Prior names, identifiers, links and changes help explain current records; stale associations remain challengeable |
| Serial/VM identifiers | Often strong identity evidence, qualified by validity, reuse, cloning, roaming, conflicting evidence and history |

Combine evidence by its meaning, quality, uniqueness, temporal relevance and
independence. Retain supporting, opposing and missing evidence. Do not count a
short name, its normalized variant, and an integration link inferred from that
name as three independent confirmations. No arbitrary additive score or fixed
number of weak matches grants action authority.

Comparison can cross source instances and platforms where claims describe the
same kind of thing. Namespaces prevent identifier collisions; they do not prohibit
comparison. Normal cross-platform corroboration is not duplicate-source cleanup.
Equivalent service functions can prompt a purpose review without proving the
installations are interchangeable or unnecessary. Outcomes can be supported same
identity, supported different identities, or unresolved, without attaching records.

## Domain contracts

**Record identity:** use the existing stable source identity: tenant, source
instance, external namespace, parent namespace/id, external id. Record type is
assessment context and a comparison-policy boundary, not a new identity field.
Transport binding, client mapping, Computer attachment, name, and changing status
do not identify the source record. Reuse existing keys; do not make source evidence
an Operations entity merely to give findings a subject (ADR-0012).

**Evidence:** retain original source attribution, raw-versus-normalized provenance,
record class, presence/snapshot completeness, reported connectivity, field-specific
timestamps and validity, current identifiers, relevant history and operator decisions.
Expose only authorized safe metadata. A collection time, activity time, connection
event and installation creation time remain different facts. Missing/sentinel values
stay unknown; disagreement does not automatically establish which producer is wrong.

**Assessment:** each applicable rule returns measured no-discrepancy,
measured discrepancy, unknown, or not applicable, with evidence, policy version,
freshness, and explanation. These are conceptual results to map onto the existing
condition-response contract, not a new status system or general Readiness UI.
No-discrepancy is not a global certificate for all claims or record purpose.
Every scoped record can be assessed; that does not require a finding for each record.
Identity pending must not turn this into merely optional future evaluation.
Attempt applicable non-identity rules now; name exactly which missing inputs limit
a particular rule. Never use unresolved identity as a blanket assessment blocker.

**Purpose:** policy must describe each record class's legitimate role and exceptions.
Operational agents represent actual service installations; VM inventory represents
VM objects, not proof of agent coverage; documentation can represent equipment,
locations, history, or other assets; organization records supply source grouping.
An absent Computer requirement does not make an installation unnecessary. Historical
retention can justify a record. Unknown purpose alone does not prove cleanup eligibility
or require every record to receive manual approval.

## Conditions and decisions

| Concern | Eligibility | Resolution and closure |
| --- | --- | --- |
| Identity uncertainty | Concrete contradictory identity evidence, ambiguous supported association, or qualified unmatched identity work under reviewed policy; attachment not required | Existing guarded identity actions or source correction; reassess the exact conflicting evidence |
| Incorrect attribution | Source group/client assertions conflict or require mapping | Existing mapping/ownership workflow; record-level association never maps the whole group |
| Incorrect source/normalized data | A source-specific field or reference rule establishes a discrepancy, not merely absence of optional data | Correct the responsible source, parser, projection, or association; verify corrected evidence at that boundary |
| Possible duplicate source records | A reviewed combination of strong or weak evidence supports a meaningful unresolved question about distinct entries representing the same object/role; neither serial nor VM UUID is mandatory. A shared name alone initiates comparison rather than automatically creating an issue | Review identity and role first. Different machines resolve the duplication concern; source inaccuracies remain separate. Equivalent records alone do not authorize cleanup |
| Proven replacement | Source policy establishes the same underlying object and explicit supersession, or sufficiently complete installation/activity chronology establishes succession without conflicting evidence | Immediate cleanup review under ADR-0048; no extra age gate. Source correction/archive/removal remains explicitly authorized and verified by refresh |
| Qualified staleness | Valid source-specific contact/activity evidence exceeds an approved threshold, with expected offline/archived cases and collection health accounted for | Source maintenance review. No configured threshold or adequate timestamp means unknown, not stale |
| Unjustified record/installation | Evidence establishes that continued existence lacks the applicable operational/documentation/retention justification, or a specific consequential purpose question remains unresolved | Establish the needed disposition; distinguish correcting/removing a source entry from removing an installation. Missing requirements alone do not establish redundancy |
| Missing required representation/service | An explicit service, inventory or documentation expectation applies and sufficiently complete evidence establishes a gap | Fulfill that expectation and verify it; retaining or attaching another record is not automatically fulfillment |

These are domain concerns, not a list of new finding types. An identity
question and a duplicate-cleanup question may share a workspace while remaining
different corrective actions (ADR-0043). Same-name records with different usable
serials are not inherently defective. Simultaneous activity with matching hardware
needs source-specific interpretation; do not add a universal merge/split rule.
Proposed changes to ADR-0032 require explicit amendments. Justify operator
separations by their exact evidence/scope and reconsider them on relevant changes.

Replacement must never follow merely from newer receipt, same serial/MAC, current
online/offline contrast, missing contact, or a free-text note. The three measured
ScreenConnect pairs do not pass a proven-replacement test with the retained history.
ScreenConnect connection events can be shown alongside LastActivityTime; using
them as interchangeable contact timestamps needs an explicit source contract.

## Work identity, visibility, and operator flow

Use one work identity per underlying discrepancy and corrective action, anchored
to stable source targets and rule/action scope. Attachment and client changes do
not create a new episode. Grouping is presentation over that work, not a second
queue or a count per participating record. Changed membership needs explicit
episode/history reconciliation rather than silently closing/recreating work.

Source Records offers Review for a record or related record set. Its review
workspace compares records, explains why they were compared, shows contrary
evidence and separate attribution, and offers applicable existing guarded actions.
It must work without a Computer. Computer/client pages link the same evidence;
possible matches are visibly different from attachments and ownership assertions.
Reuse existing review workspaces/routes where they can satisfy this contract.

The workspace must perform the investigation it can support, rather than hand
the operator a set of records to investigate again. Each concern presents the
question/discrepancy, exact targets, evidence provenance and adequacy, competing
explanations, supported conclusion, recommended correction and reason, remaining
specific judgment, action authority, and the observable closure test. One record
can have independent concerns; one concern can involve several records.

For the measured ScreenConnect pairs, show likely same-hardware evidence,
online/offline source assertions, different customer attribution and missing
replacement chronology. Keep association, attribution and maintenance conclusions
separate. Do not recommend deleting the disconnected member as proven replaced.
Automatic association remains possible where a justified reviewed policy and
ownership checks support it, including name-based rules. A weak indicator's
inability to prove identity alone must not erase its discovery or explanatory value.

Issues, summaries, HTML and export use PLAN-003's common selection/count contract.
Unassigned work remains visible in authorized global scope; likely-client context
does not assign ownership or multiply the global count. No synthetic Computer or
fake binding subject may be created to pass an eligibility check. The shared subject
adapter must preserve exact record targets and optional canonical context; its schema
and permissions require PLAN-003 coordination before implementation.

Unresolved identity retains the accepted Critical severity independently of confidence.
That is not a blanket Critical rule for every unassigned record, missing timestamp,
or maintenance case. Other severities require explicit domain policy. Explain an
unavailable action beside it without inventing a Waiting/Blocked issue category.

## Reassessment, closure, and exceptions

Reassess after relevant source snapshots, identifier/material changes, mapping or
attachment decisions, and policy changes. Contact-based rules also need time-driven
evaluation because age can cross a threshold without a material change. Partial
or failed collection cannot establish absence or source-repair closure; loss of
measurement does not clear a previously established discrepancy.

Source correction closes only after a successful applicable refresh establishes
the corrected state or supported withdrawal/archive outcome. A merge/attachment
closes only the association concern it resolves. Preserve operator history across
reappearance. Any accepted exception records its evidence/action scope, reason,
actor, and expiry or changed-evidence trigger; new contradictory evidence is not
hidden by the old decision. No deletion of canonical entities follows source absence.

## Compatibility mapping and accepted decisions

The following maps existing behavior to the proposed needs. It does not constrain
which domain assessments the completed design must support or require preserving
an inadequate implementation boundary.

- Extend `duplicate_platform_record` coverage to eligible unattached evidence;
  fix instance/namespace comparison boundaries. It remains source review, not
  proof of replacement or an instruction to delete the older entry.
- Assess `unlinked_external_identity` reuse for qualified unresolved identity;
  registration alone does not provide a producer or an adequate subject contract.
- Retain mapping findings where they own mapping actions; reconcile overlapping
  entity/admin rows by exact action scope, preserving independent source corrections.
- Preserve exact Hudu archive targets and separate incorrect-link repair. Expand
  applicability only with safe subject support, not by fabricating client ownership.
- Do not revive retired source-withdrawal findings or use whole-Computer stale-data
  and required-agent findings as individual-record cleanup work.
- ADR-0048 remains accepted for attachment and replacement/staleness paths. Broader
  data correction/purpose rules need reviewed contracts, not an implicit extension
  of deletion eligibility. ADR-0032's managed-admission intent is required; clarify
  its distinction from completed Computer association. No blanket manual matching
  or attachment suspension is proposed.

## Implementation proposal boundary and acceptance

No code is selected yet. Likely affected areas are source evidence/state contracts,
record comparison and identity evaluators, finding adapters/assessments, safe reads,
Source Records and existing resolution workspaces, and PLAN-003 consumers. Preserve
connectors as evidence producers and existing projector write ownership. Any new
schema/type, indexes, data repair, or public interface needs its own reviewed design.

Before implementation approval, resolve: per-stream comparison roles and replacement
proof; stale thresholds and timestamp semantics; safe record-target subjects/actions;
exception scope; condition identity/membership migration; exact type reuse/severity;
bounded comparison query strategy; and cutover/rollback preserving existing episodes.
These are design details to settle, not reasons to resume fleet discovery now.

Acceptance: the measured unassigned/attached pairs are reviewable before association;
an isolated record can reveal an inaccurate field or unjustified purpose; name-only
and MAC-only evidence can discover comparisons without automatic identity/cleanup
conclusions; variants/history/domain/reference/timing context remains visible;
relayed or normalized copies do not inflate corroboration; cross-source comparisons
remain possible without conflating namespaced IDs; explicit missing documentation
and services are assessed separately from existing-record quality;
unknown contact does not negate connected state or manufacture age; distinct-machine
same-name pairs do not become cleanup tasks; attachment does not clear independent
maintenance; a proven replacement bypasses age; no proof/threshold fails closed;
partial snapshots do not clear issues; reappearance reopens the right concern;
source-instance/namespace boundaries, restricted records and tenants remain isolated;
HTML/export/counts reconcile without duplicate action rows. Validate guarded identity
actions and operator exceptions under the runtime role and actual PostgreSQL, with
performance checks on bounded comparison candidates. No source mutations in tests
against production. Implementation and execution remain separately authorized.
