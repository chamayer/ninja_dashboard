# PLAN-004 — Identity and source-record maintenance review

## Status and goal

Revision 8 design **accepted by the user, 2026-10-29**, after independent review.
Case combining (PLAN-033) and source-record notifications (PLAN-034) are deferred.
No implementation or production execution is authorized yet.
Managed admission and evaluation remain independent of identity completion.

## Scope and authorities

- [Final design](PLAN-004-source-record-final-design.md): controlling contract.
- [ADR-0049](../decisions/0049-managed-record-evaluation-before-identity.md):
  decision list and explicit amendments to earlier scoped directions.
- [Review summary](../records/PLAN-004-design-reconciliation-2026-10-29.md):
  removed/retained scope, list-item dispositions, tradeoffs and validation.
- [PLAN-003](PLAN-003-technical-design.md): protected common-store integration.
- Deferred [PLAN-033](PLAN-033-source-record-case-combining.md) and
  [PLAN-034](PLAN-034-source-record-notifications.md): brief placeholders to improve
  on activation, not prerequisites for the smaller release.
- [Technical inventory](PLAN-004-source-record-technical-design.md) and
  [retained evidence](../records/PLAN-004-record-evidence-2026-10-29.md): context,
  not authority to restore removed scope. Registry owns lifecycle.

## Decisions, files and steps

Core: durable subjects, one association authority, independent code-defined rules,
conservative names/identity policy, native assessments/findings/history/actions,
simple one-key cases, tenant/RLS/permission protection and legacy notifications.
Keep a coarse tenant shared/exclusive guard plus transactional input generation;
remove per-key plans/counters/tickets. One assessment/publisher worker initially;
indexed neighbor scheduling plus a conservative coalesced refresh loses no work.
New native types are UI-only. No case combines, activation cutoff/sweep, fingerprint
conversion, release ledger, route framework or dispatcher redesign. Record rule/config
revision. Maintenance has an approved window/abort procedure, not invented timing.

Design files: final design, ADR, PLAN-003 text, this handoff, summary, PLAN-033/034,
router/registry. Unrelated dirty work is preserved; no code or migrations changed.

## Checkpoint, validation and next action

Checkpoint: revision 8 independently reviewed and accepted; ADR-0049 accepted.
Validation: registry, scoped links/whitespace, single-H1 structure, root governance
metadata and router/handoff sizes pass. Review found no blocking defect.
Review notes for the representative load check:
- The tenant-wide input generation discards in-flight publications on any input
  commit, so continuous ingest may delay publication. Measure it. Any remedy must
  keep complete input freshness: a target-only check is not acceptable, because
  another record can change a comparison without changing the target.
- The single counter row serializes concurrent intake commits; measure that too.

Ownership and order: PLAN-003 owns the tenant guard helper, common findings,
relationships and queue/counts; no interim finding write path. Approved release
order R0–R4 plus the reassessment operation is in
[PLAN-003 current design](PLAN-003-current-design.md#joint-implementation-order-with-plan-004-approved-2026-10-29).
PLAN-004 ships in R4: Stages A and C, then the association handoff once its
prerequisites exist (coordinated release). Code may be developed in parallel.
R0 complete ([baseline](../records/PLAN-003-004-R0-baseline-2026-10-29.md);
missing association writers added to §2.1). Next: PLAN-003 R1.
No runtime/PostgreSQL/concurrency/load/browser/rehearsal/production checks ran.
Implementation, maintenance, migrations, source actions, commit and deployment
retain separate approval gates. Prior status/contact deployment evidence stays in
its [checkpoint](PLAN-004-source-record-status.md).
