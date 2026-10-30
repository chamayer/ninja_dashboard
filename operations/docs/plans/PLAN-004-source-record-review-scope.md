# PLAN-004 — Source-record review scope and prior checkpoint

Retained scope, evidence, and acceptance detail from the review handoff before
the needs-first review on 2026-10-29. The current checkpoint is
[PLAN-004-source-record-review.md](PLAN-004-source-record-review.md); current
needs analysis is [PLAN-004-source-record-needs.md](PLAN-004-source-record-needs.md).
Earlier next actions below are historical; neither this record nor the needs
review expands runtime approval.

## Status and authority

Active review, authorized 2026-10-28. This document retains the detailed scope for
PLAN-004. On 2026-10-28 the user separately approved local implementation of
the [per-record status/contact repair](PLAN-004-source-record-status.md), its
additive metadata-view migration, tests, and plan updates. ADR-0048 records the
separately accepted attachment and cleanup policy direction. Broader implementation,
schema changes, reattachment, group mapping, source cleanup,
recalculation, commit and deployment remain outside that approval.
The registry retains PLAN-004's earlier lifecycle and follow-ups. Historical
identity design remains in the previously registered archive.

## Goal and ownership

Review the complete source-record lifecycle, including records with no client
or Computer. Operators must discover identity uncertainty and source cleanup
work without finding the record manually or querying another system.

PLAN-004 owns evidence qualification, matching, candidate eligibility, identity
and duplicate predicates, source-record maintenance conditions, resolution and
Computer/source-record evidence. PLAN-003 owns the common finding store and
relationships, Issues eligibility/counts/filtering/export, and dashboard
presentation. Review the domain rules here before finalizing their PLAN-003
adapters. PLAN-015 retains its separately approved one-time reconciliation;
PLAN-025 retains ScreenConnect collection/configuration; PLAN-031's state-label
change is complete and does not repair detection.

## Confirmed review findings

Production was inspected read-only on 2026-10-28. The deployed revision was
`b393c57`; local identity files contain unrelated edits and are not deployment
authority. No new fleet-wide impact count is claimed.

1. Two ScreenConnect sessions can report matching serial and MAC while only
   the older offline session is attached. The newer online session can remain
   unassigned because its source customer group has no mapping. Resolver jobs
   completed after collection; this case is not merely a pending resolver run.
2. Enabled serial/VM UUID/name policies require client scope. Only the existing
   source-identity shortcut can run without it. Promotion also requires a
   client. The unmatched session's candidate is observed_only, without a
   proposed Computer. Evidence exists without actionable identity review.
3. Duplicate-platform detection joins observations to existing Computers.
   Shared-serial and cross-client checks likewise consume attached evidence
   or established Computers. They omit a strongly matching unlinked record.
4. ScreenConnect duplicate hints group by customer value and normalized name;
   differing names and groups can escape that hint despite matching hardware.
5. A record remains present when a complete source response still contains it.
   ScreenConnect excludes ended/deleted sessions, but a free-text stale-session
   note does not withdraw one. Collection time does not establish device
   activity or the duration of inactivity. The investigated old record had an
   unknown record lifecycle and counted as current Computer evidence.
6. Required-agent staleness and whole-Computer stale-data findings do not own
   individual source-session cleanup. The retired source-withdrawal finding
   must not be revived as a generic cleanup rule.
7. Computer-page evidence is primarily attached-record evidence. Strong matches
   that remain unlinked are buried in source inventory. Existing candidate
   queue routes redirect to Issues; observed_only evidence is not actionable
   pending work. There is no complete current workflow for this case.
8. Entity and admin findings must both be audited. A separate existing admin
   duplicate finding was found for the example Computer; checking only the
   entity ledger would miss it. Its currentness requires reevaluation review.

## User requirements and design boundaries

- Surface strongly matching unassigned records on the likely Computer page,
  with the supporting identifiers, source state, and unresolved attribution.
  A possible association must remain visibly different from an attachment.
- Extend existing duplicate-platform detection to this evidence boundary.
  Corroboration of one machine across different platforms is normal; multiple
  identities in one source can require cleanup. Respect source instances and
  record types when defining that duplicate boundary.
- Unresolved identity findings are Critical, with client-mapping prominence
  on fleet/client summaries. Confidence remains independent. Unassigned work
  stays visible globally; likely-client visibility must not assert ownership
  or multiply global issue counts.
- Preserve original source-group attribution independently of inferred
  identity. Matching an individual record must not map its entire group or
  hide evidence of another client's ownership.
- Source records need maintenance findings even without a Computer or client.
  Retain a source link, supporting timestamps/state and corrective action.
  Source cleanup occurs at the source; successful refresh establishes closure.
- ADR-0043 keeps source-record duplication separate from the consolidated
  Computer-identity case; ADR-0040 owns client conflicts. Reuse existing types
  where corrective actions match. A source-record-staleness condition is a
  proposed new type, subject to the inventory/reuse review below.

Accepted policy direction is recorded in [ADR-0048](../decisions/0048-source-record-attachment-and-cleanup.md):
attach newly supported unassigned records automatically for a unique,
corroborated match passing all reviewed identity/ownership checks; retain
unresolved source-group mapping and route ambiguity/conflicts to review.
A serial is strong evidence, MAC is supporting evidence (ADR-0032), and neither
alone resolves ownership. Review uniqueness, rejected/roaming values, virtual/shared adapters,
re-enrollment, reused hardware, conflicting identifiers, simultaneous source
activity, historical source identity and explicit operator separations. Preserve
automatic matching already accepted by ADR-0032 unless a reviewed amendment
changes it; do not introduce blanket manual name matching.

## Full review and deliverables

| Area | Required review and output |
| --- | --- |
| Collection and identity keys | Inventory every enabled stream from registries; distinguish instance, namespace, parent, record type and external ID. Review snapshot completeness, partial failure, pagination and withdrawal/reappearance. |
| Source state | Define per-stream meanings of present/withdrawn, reported status, activity/contact, last received/observed, deletion and vendor notes. Identify absent/invalid timestamps and source-specific inactivity evidence. |
| Matching | Trace new, linked, unassigned, identifier-changed, renamed, reinstalled, transferred, offline/retired and operator-separated records. Record each skip/blocker and whether review work is created. |
| Identity/ownership | Separate physical identity evidence from source attribution and Computer ownership; design safe possible-match evidence and cross-client conflict handling without silently inheriting away uncertainty. |
| All findings | Inventory producers, ledgers, subjects, participants, identity keys, predicates, severity, actions, assessments and closure. Classify active, dormant, retired and proposed types. Reconcile registry descriptions against actual code. |
| Duplicates and cleanup | Review source-record duplicates, shared identifiers, split Computers, two machines on one Computer, stale sessions and source-group problems. Define distinct corrective actions and any legitimate Covers/Requires relationships. |
| Visibility and actions | Audit Computer/client pages, Source Records, source detail, Issues, fleet summaries, admin evidence, exports, permissions and audit/history. Show unassigned records and original evidence safely. |
| Fleet evidence | Measure anonymous aggregates in an authorized consistent production read. Count strong unlinked matches, ambiguity/conflicts, duplicate groups, absent client scope, stale/unmeasurable timestamps and overlap among issues. Do not infer fleet scope from this single example. |
| Implementation design | Produce proposed predicate/subject/action contracts, affected files, any new type, schema/data effects, migration/cutover/rollback and validation before seeking implementation approval. |

Cleanup review qualifies immediately when replacement is proven; otherwise it
qualifies when the record becomes stale. No additional stale-age wait applies
to a proven replacement. The replacement predicate, applicable source-specific
stale thresholds, exceptions and severity still require technical design.
This direction does not authorize automatic source deletion. Offline alone,
a stale collection, a sentinel timestamp or a vendor note must not invent a
duration, prove disappearance or trigger cleanup automatically. Expected
long-offline/archived records and sources reporting no contact need defined
treatment. Reappearance and source repair must reconcile existing episodes.

## Validation required before implementation closeout

Validate with representative PostgreSQL/runtime-role cases: attached plus
unlinked duplicates; unknown versus conflicting client; serial reuse/clones;
MAC-only, placeholder and roaming evidence; simultaneous and sequential
agents; source-instance/namespace collisions; missing and contradictory state;
partial snapshots/failure; repeated evaluation; source cleanup and reappearance;
operator exclusions; restricted records; tenant isolation; HTML/CSV counts and
source/Computer/client drill-throughs. No synthetic customer payloads in Git.

## Checkpoint and next action

Initial production/code review established the gaps above. The separately
authorized [aggregate review](../records/PLAN-004-source-record-review-2026-10-28.md)
measured unassigned records, duplicate-finding reconciliation, timestamp limits
and per-record display mismatches. The approved [status/contact repair](PLAN-004-source-record-status.md)
is deployed in 0.130.1 (`c7628b9`), with migration 0361 and read-only production
verification recorded in its checkpoint. Full domain/state
contracts and final finding reuse/new-type decisions remain pending. Automatic
attachment and cleanup timing now have accepted policy direction in ADR-0048;
their exact predicates and enforcement remain to design. No resolver or cleanup
behavior changed.

Current focus (2026-10-29): the user is reconsidering whether every source
record has a justified purpose and accurate evidence independently of Computer
identification, with Computer requirements assessed additionally. Current code
has separate mapping, identity, quality, coverage and Hudu-maintenance checks;
duplicate and several quality checks depend on an existing Computer. No common
record-purpose/accuracy assessment was found in these paths. This is a review
question, not a new approved policy or runtime change; reconcile it with ADR-0048.

Next: define the distinctions between record justification, evidence accuracy,
identity/ownership and Computer requirements, then resume the producer/consumer
matrix. Continue in a fresh session with this handoff and current Git state.
Coordinate PLAN-003 before changing shared subjects or finding persistence.
