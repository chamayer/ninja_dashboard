# PLAN-004 — Revision 8 simplification and review summary

Date: 2026-10-29. User authorized this document rewrite and two brief deferred
plans. Independently reviewed and accepted by the user on 2026-10-29. No runtime
changes, production discovery, implementation or deployment authorized.

## Original intent retained

Every received source record is managed/evaluable from intake without waiting for
Computer identity or client mapping. Independent rules retain explicit unknowns;
comparisons include useful names/MACs without assuming identity. Findings, history,
applicable guarded actions, one association authority and preview/review/apply
reassessment remain. Tenant/RLS/restricted-record protection is mandatory.

Two capabilities are explicitly deferred: combining investigations, and alerts for
new native source-record findings. Related cases remain visible side by side; new
native findings are UI-only while existing legacy notifications continue. This
is a smaller first release, not a claim that those features have equivalents now.

## Disposition of the simplification list

| Items | Revision 8 change |
| --- | --- |
| 1 | Retain two coarse guard categories: shared input-only and exclusive graph/publication/action. Remove the large per-writer mode matrix; keep the association-writer inventory. Target-only version checks cannot catch another record changing a comparison |
| 2–3, 5 | Remove per-key lock plans, sorted hashes/namespaces, bucket table/counters and optimistic key-plan retry machinery. One transactional tenant generation, one assessment/publisher worker, indexed neighbor enqueue and coalesced paged refresh protect freshness and eventual dependent work |
| 4 | Remove invented millisecond/throughput targets, tuning ladder and ticket fallback. Keep configured timeouts, overall transaction deadlines, bounded batches/retries and representative concurrency/load checks before deployment |
| 6–9 | Remove combines/splits, survivor aliases, redirects, repointing, multi-anchor claims, 32/500 limits and reviewed_case_equivalence matcher. One shared-key case/question with a finding; paging and related-case workspace. Audited duplicate references preserve history, block immediate recreation while valid and do not imply correction |
| 10–14 | Remove notification baseline/release lineage, material-release revisions, exact-set activation sweep, staged successor conversion, cutoff/pause/fallback/catch-up and alias/max-merge machinery from this release. New native type keys default non-alertable; legacy types/IDs/fingerprints/targets/state remain. No first-opened-time eligibility rule is adopted |
| 15–17 | No route-principal framework, special no-route state or dispatcher protocol redesign. Existing dispatch remains; add no member payload context. Access controls remain and any necessary new context defaults to minimal text plus permission-checked UI links |
| 18–20 | Three stages: A managed records/independent rules; B association authority/reassessment in an approved maintenance window; C simple cases/workspace. Remove E3R/E4 preactivation machinery and arbitrary outage budgets. Verify additive compatibility; coordinated incompatible/PLAN-003 cutovers and approved abort/recovery remain |
| 21 | Code-defined rules/config values with recorded revision; remove immutable rule-policy JSON/digest machinery |
| 22 | Short status, one controlling decision list, compact handoff/registry routing and this summary. Mandatory repository governance remains; do not duplicate the design across status records |

The coarse generation deliberately invalidates unrelated in-flight comparisons and
adds a short shared counter-row serialization point. Its simpler safety model is
not a performance claim; continuous-ingest races and representative load must be
validated before rollout. Never silently drop generation checks to meet throughput.

Legacy/native finding ownership is an explicit implementation inventory: a proven
legacy-owned correction links to its existing finding instead of emitting a duplicate.
Ambiguity blocks that new rule's finding activation, not intake or independent
assessment. Independent qualified case questions still each receive a finding.
Reassessment may legitimately change existing legacy findings/alerts; preview and
review that operational consequence rather than claiming notification behavior
cannot produce any messages.

## Deferred plans and amended decisions

- [PLAN-033](../plans/PLAN-033-source-record-case-combining.md): brief case-combining
  placeholder; refine requirements and validation when explicitly activated.
- [PLAN-034](../plans/PLAN-034-source-record-notifications.md): brief notification
  placeholder; decide eligibility, visibility and continuity at activation.
- [Backlog](../../TODO.md): revisit coordination/policy complexity only on measured need.

[ADR-0049](../decisions/0049-managed-record-evaluation-before-identity.md) explicitly
amends earlier decisions 2 and 4 and defers 5–7. Authority/reassessment, fresh
publication, independent evaluation and conservative identity policy stay. These are
reviewed-draft scope amendments, not claims of accepted/deployed runtime changes.

## Review package and validation

Read the [final design](../plans/PLAN-004-source-record-final-design.md), ADR-0049,
[PLAN-003 integration](../plans/PLAN-003-technical-design.md) and the two brief plans.
The [handoff](../plans/PLAN-004-source-record-review.md) owns the current checkpoint.
Supporting technical drafts are inventories and cannot reintroduce removed scope.

Checks pass: registry (34 entries), scoped relative links/whitespace, single-H1
structure, root governance metadata (size/headings and VERSION/CHANGELOG agreement),
router/handoff sizes and tracked scoped `git diff --check`. Untracked documents
were checked directly too. Author consistency review covered guard/generation,
legacy/native type ownership, case lifecycle, rollout and explicit deferrals.
The controlling design shrank from 1,136 to 541 lines; both deferred plans are 28 lines.
No runtime, PostgreSQL,
concurrency/load, browser, rehearsal or production checks ran. Local writer evidence
comes from a dirty worktree; implementation must re-inventory its actual release.
Independent review found no blocking defect; the user accepted the design.
No commit or push.
