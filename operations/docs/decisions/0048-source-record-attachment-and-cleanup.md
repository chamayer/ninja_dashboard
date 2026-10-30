# 0048 — Unassigned-record attachment and replacement cleanup

Status: Accepted policy direction; detailed contracts and implementation pending.
Date: 2026-10-28

## Context

The PLAN-004 review found unassigned source records with strong identity evidence
and older records still present beside their replacements. The user accepted
automatic attachment for qualified matches, preserving unresolved source-group
mapping, and specified cleanup review immediately after replacement is established,
otherwise when the record becomes stale.

## Decision

1. Newly supported unassigned records may attach automatically when the match is
   unique and corroborated and all reviewed identity and ownership checks pass.
   Ambiguous or conflicting cases require review. Preserve automatic matching
   already accepted by ADR-0032; this is not a new manual-only matching policy.
2. Attachment of one record never maps its entire source group. Original source
   attribution remains independently visible, including unknown mapping and
   contrary ownership evidence. A possible match remains distinct from attachment.
3. A record proven replaced becomes eligible for cleanup review immediately,
   without waiting for a stale-age threshold or an additional grace period.
   Another record being newer, or corroboration from another platform, does not
   by itself establish replacement. PLAN-004 must specify the evidence test.
4. Otherwise, a record becomes eligible for cleanup review when it becomes stale
   under its applicable reviewed source policy. There is no approved numeric
   threshold yet and no added arbitrary waiting period after staleness qualifies.
   Source-specific timestamp meanings and expected offline/archived cases matter.
5. These are finding/review eligibility rules, not automatic deletion authority.
   Cleanup occurs at the source. Successful refresh establishes closure; retain
   history and reconcile reappearance. Unknown contact duration cannot be
   manufactured from collection time, a sentinel timestamp or a vendor note.

## Enforcement and validation to implement

No resolver, evaluator, action, schema or source behavior is changed by this ADR.
PLAN-004 must define and validate the unique-match, corroboration, rejection,
roaming, clone/reused-hardware, conflicting-identifier, historical-identity and
operator-separation guards before implementation. Preserve ADR-0032's existing
rules unless a further reviewed amendment changes them.

The maintenance evaluator must apply two explicit predicates: proven replacement
without an age gate, or qualified source-record staleness. Tests must distinguish
replacement from coexistence and normal cross-platform corroboration; cover
ownership conflicts, missing contact, source-instance/namespace boundaries,
expected offline records, source correction, reappearance and tenant isolation.

PLAN-003 consumes the resulting subjects, action identities, closure evidence and
counts. ADR-0040 continues to own client conflicts; ADR-0043 keeps source-record
cleanup distinct from the Computer identity case. Finding reuse, source-specific
stale thresholds, severity, migration and cutover remain technical design work.

## Review clarification — 2026-10-29

The user directed PLAN-004 to start from source-record correctness and purpose,
independently of attachment. This ADR neither requires attachment before review
nor certifies a record's accuracy or justification when it attaches. The design
must support the clarified managed-admission requirement: every record
participates in Operations evaluation and findings immediately; identity completion
never gates unrelated evaluations. This does not by itself choose a canonical
entity or structured-reference implementation for that managed identity. The
accepted replacement/staleness cleanup-review paths remain unchanged. They do not settle
the broader treatment of inaccurate recent records, equivalent live installations,
or unjustified records without proven replacement. The
[needs review](../plans/PLAN-004-source-record-needs.md) and
[proposed design](../plans/PLAN-004-source-record-design.md) must establish those
contracts before an amendment or implementation is approved. No new cleanup,
attachment, or source-mutation authority is granted by this clarification.

The completed [final proposal](../plans/PLAN-004-source-record-final-design.md)
and proposed [ADR-0049](0049-managed-record-evaluation-before-identity.md) now
select durable native record/case subjects and the explicit evaluation/action
contracts. This completes the design choice; approval/implementation remain separate.

## References

- [PLAN-004 review](../plans/PLAN-004-source-record-review.md)
- [ADR-0032](0032-computer-identity-matching-and-merge.md)
- [ADR-0040](0040-client-source-mappings-are-recorded-and-movable.md)
- [ADR-0043](0043-one-machine-or-two.md)
