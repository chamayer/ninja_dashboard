# PLAN-004 — Source-record correctness and maintenance needs

Status: Needs review developed, 2026-10-29; no runtime implementation approved.
The [final design](PLAN-004-source-record-final-design.md) is now the controlling
proposal; the discussion below retains needs/evidence rationale.
The user stopped discovery and requested the
[proposed design](PLAN-004-source-record-design.md). The
[October 29 evidence](../records/PLAN-004-record-evidence-2026-10-29.md) distinguishes
measured cases from the possible explanations below; not all scenarios are observed.
The [handoff](PLAN-004-source-record-review.md) owns the current checkpoint.

## Basis and scope

User direction: assess source records independently of Computer attachment.
The user clarified the reason every record must attach/be managed: each must
enter Operations as a managed evaluable item immediately, including for findings
unrelated to identity. No record waits for identity completion before further
evaluation. Final Computer association and managed admission are distinct needs.
Two active records with equivalent functions first raise a data-quality question:
are they really the same machine? Attachment cannot be a prerequisite for that
investigation or proof of its answer. This review develops that direction;
unsettled policy and proposed acceptance cases below are not implementation approval.

The need is trustworthy source inventory: understand what exists, whether records
describe it accurately, whether their continued existence is justified, and what
correction is needed. A source record, an installation/session, and a machine are
different things. A documentation record may describe something other than a
Computer. Equivalent functions do not prove equivalent identities.

Computer identification, ownership, and requirements supply additional questions.
They do not determine which source records may be reviewed. Tenant authorization
and restricted-record permissions still apply; lacking a client mapping does not
make evidence public or globally unscoped.

## Questions the review must answer

| Question | Evidence needed | What does not answer it |
| --- | --- | --- |
| What does the record represent? | Record class, source identity, described object, installation/session identity, and relevant history | Its attachment, name, or function alone |
| Do apparently related records describe the same thing? | Comparable usable identifiers, temporal evidence, conflicts, source boundaries, and recorded separations | Shared MAC/name alone, or a shared Computer attachment |
| Are its claims accurate? | Field meanings, provenance, direct versus relayed evidence, validity, timestamps, and corroborating or contrary evidence | Majority agreement, successful collection, or a source status label alone |
| Is continued existence justified? | Actual operational role, distinct installation purpose, documentation scope, or applicable retention need | Presence, recent activity, or absence of a known replacement alone |
| Is expected representation missing? | An independently established expectation and adequate collection/evaluation coverage | Absence from a failed or partial snapshot; a blanket requirement for every record |
| What resolves the concern? | The discrepancy, exact target, responsible correction, and observable verification | Attaching the record, dismissing a row, or correcting an unrelated concern |

Accuracy is assessed by claim and intended use, not as a blanket good/bad label
for the record. An old value can be correct historical information but unsuitable
as current identity evidence. Missing evidence is unknown unless the source
contract actually requires it. Contradictory claims justify investigation without
automatically establishing which source is wrong. Collection, normalization,
relay resolution, and our own association can each introduce the discrepancy.

Justification is also specific to the record. The tool's purpose does not explain
every entry in it. An accurate record can be unnecessary; a necessary record can
contain errors. Historical retention can be legitimate, but neither a mandatory
operator reason for every record nor a new retention policy is approved here.

## Worked case: two equivalent records reported active

| Established reality | Concern to resolve | Evidence that would establish resolution |
| --- | --- | --- |
| Two different machines | Whether names, identifiers, attribution, or our association falsely conflate them | Correct representation of each machine and correction of any misleading claim/association |
| Two installations on one machine, both actually operating | Whether coexistence is intentional and appropriate | Established distinct purpose or applicable exception; otherwise correction of the unnecessary installation and its source record |
| One current installation and an abandoned predecessor | Whether the predecessor's state and continued presence are accurate/justified | Verified replacement or qualified staleness review, appropriate source correction/archive/removal, and successful refresh |
| One installation represented twice | Source representation or collection/normalization duplication | Correction at the responsible producer and verification that legitimate evidence remains |
| Identity or activity cannot be established | Insufficient or contradictory evidence | Further evidence or a reasoned, scoped disposition; uncertainty is not proof of duplication or inactivity |

These are investigation outcomes, not automatic action rules. Even when both
installations operate, their existence does not establish that both are needed.
Conversely, equivalent functionality alone does not establish redundancy.
A single record needs the same accuracy and justification review; a second
record merely makes some discrepancies easier to discover.

## Operator outcomes and closure

The review should identify a concrete discrepancy or evidence gap, its scope,
supporting and contrary evidence, the responsible action, and how to verify it.
Possible outcomes are retain, correct, investigate, or archive/remove at the
source when authorized. Installing/removing software and deleting source records
are different actions; this review authorizes neither.

Record correction, collection/parser repair, identity association, ownership
correction, and requirement fulfillment have different closure evidence. One
action closes another concern only when it actually resolves that discrepancy.
Source repair requires a successful applicable refresh; collection failure cannot
prove repair. Changed evidence and reappearance must be reassessed. A legitimate
exception needs a defined scope and reconsideration trigger, rather than hiding
unrelated or later problems. Exact disposition and closure contracts remain open.

## Reconciliation with accepted decisions

- [ADR-0048](../decisions/0048-source-record-attachment-and-cleanup.md) permits
  guarded automatic attachment. It does not certify purpose or accuracy and
  does not require attachment before source-record review.
- Its immediate proven-replacement and qualified-staleness rules remain accepted
  cleanup-review paths. They do not establish a complete policy for inaccurate
  recent records, equivalent live installations, or unjustified records with no
  proven replacement. Those needs must be reviewed before extending that policy.
  No age threshold, extra waiting period, or automatic deletion is introduced.
- [ADR-0032](../decisions/0032-computer-identity-matching-and-merge.md) says every
  record attaches. The user clarified the intended need: universal admission to
  managed evaluation, with identity completion never a prerequisite. Reconcile
  the concrete managed target model with final Computer association and non-Computer
  roles; do not discard that evaluation requirement or silently amend matching policy.
- ADR-0040 owns client conflict actions. ADR-0043 separates source cleanup from
  the Computer identity case. Neither boundary prevents direct comparison of
  source records before a Computer is identified.
- PLAN-003's common finding store/counts consume the eventual domain contracts.
  Shared context alone does not justify merging independent corrective actions.

## Existing coverage against the need

Local code inspection; not a new production measurement or exhaustive all-type
audit. The active database condition policy and configured streams were not read.

| Existing area | What it covers | Limitation against the need |
| --- | --- | --- |
| `evaluator._evaluate_duplicate_records` | Multiple current records on one Computer, with type/layout and serial guards | Starts from attached Computers; groups by platform without instance separation; a group may have no usable serial. Does not establish replacement or purpose of each installation |
| Resolver `placeholder_serial` / `placeholder_mac` | Certain invalid identifier values on Computers/attached observations | No independent assessment of all records or all claims; valid-looking identifiers can still be wrong |
| Client resolver mapping findings and `unmatched_source_group` | Missing/ambiguous group attribution and names | Mapping success is not record correctness; overlapping entity/admin findings need lifecycle/action reconciliation |
| `identity.findings` | Computer identity and client-conflict evidence | Does not provide a general record-level review without established Computers |
| `cmdb_asset_stale` | Exact Hudu archive-candidate targets from unresolved supported relay links | Requires client scope; failed link resolution alone does not establish lack of documentation purpose |
| `cmdb_link_incorrect` | Some divergent links through resolved Computers | Client-scoped aggregation; not comprehensive per-record field/link accuracy |
| `unintegrated_source_observed` | Relayed vendor hints | Supported-vendor metadata does not establish an expected connection or a broken integration |
| Lifecycle and requirement findings | Computer inventory investigation, missing/stale required services, reporting loss | Different questions from correctness/justification of each contributing record |
| `unlinked_external_identity` | Registered unresolved identity vocabulary | No emitting ingest producer found; historical zero count does not prove retirement or suitability for this broader need |

Evidence: [evaluator](../../../ingest/evaluator.py),
[resolver](../../../ingest/identity/resolver.py),
[client resolver](../../../ingest/identity/client_resolver.py),
[identity findings](../../../ingest/identity/findings.py),
[CMDB findings](../../../ingest/cmdb_findings.py), and
[Hudu connector](../../../ingest/connectors/hudu.py).
The [October 28 aggregate record](../records/PLAN-004-source-record-review-2026-10-28.md)
retains measured gaps and limitations; counts are historical, not today's fleet.
The [PLAN-003 current design](PLAN-003-current-design.md) retains Hudu and
corrective-action boundaries. Repository profiles are bootstrap evidence, not
authority for live active types or assessments.

## Review acceptance and remaining decisions

Proposed acceptance cases: the same discrepancy stays reviewable when attachment
or client mapping is absent; a deliberately wrong attachment is challengeable;
two genuinely active equivalent installations are distinguished from stale
source state; two machines sharing bad identifiers remain distinguishable; a
legitimate historical/non-Computer record is retained; partial collection cannot
prove absence or closure; missing evidence remains unknown; correcting one field
does not erase an independent concern. All visibility respects tenant and record
permissions, and neither comparisons nor client drill-throughs multiply the work.

Next design work: establish per-stream record/object distinctions, valid purposes,
claim meanings and adequacy of evidence, including what can be checked without
identity. Then specify which discrepancies warrant work, legitimate exceptions,
and resolution evidence. Only afterward map needs to existing finding types,
identify necessary policy amendments, and propose implementation. Severity,
thresholds, schemas, subject keys, storage, automation, and source actions remain
undecided except where previously accepted decisions already apply.
