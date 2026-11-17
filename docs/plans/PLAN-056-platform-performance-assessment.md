# PLAN-056 — Platform performance recovery

## Goal and authority

The [registry](../records/PLAN_REGISTRY.md) owns
status; [consolidation](../records/PLAN-056-consolidation.md) retains prior scope.

## Scope and gates

Preserve numbered baselines. Settled requires user-accepted correctness/full-page
evidence, acceptance as-is or explicit deferral, recorded in the
[acceptance record](../records/PLAN-056-release-acceptance.md). Samples alone do not settle pages.

User authorized all-worktree reconciliation/deployment, with light tests. Follow
the [release checkpoint](../records/PLAN-056-worktree-reconciliation.md). No local fleet/timing run. Follow the
[global read contract](../decisions/0006-platform-read-contract.md).

## Current checkpoint and evidence

Deployed: `0e04294a` / 0.144.25, 0419 applied. Resume via the
[Operations checkpoint](../../operations/BLUEPRINT.md).
[Triage](../records/PLAN-056-emergency-triage-2026-11-17.md) retains live evidence;
[Source Records comparison](../records/PLAN-056-source-records-contract-check.md)
retains withdrawn-candidate limits. Worktree candidates are now reconciled.
Root TODO owns deferred resource interaction; the
[checklist](../records/PLAN-056-assessment-checklist.md) retains broader acceptance.

## Fixed numbered navigation worklist

2026-11-11 baseline: one admin internal HTTP request/page, all 200/completed.
Seconds cover HTML, not browser/network; cold state unproven. All items OPEN.
Home: <=1.5 s ordinary / <2 s hard maximum including cold navigation.

1. **Software — OPEN — 13.094 s.** Current item.
2. **Inventory: Source records — OPEN — 7.700 s.**
3. **Admin: Sources — OPEN — 6.346 s.**
4. **Inventory: Clients — OPEN — 5.793 s.**
5. **Home — OPEN — 5.688 s.**
6. **Inventory: Computers / Coverage — OPEN — 4.605 s.**
7. **Patching — OPEN — 4.349 s.**
8. **Clients — OPEN — 3.804 s.**
9. **Issues — OPEN — 2.214 s.**
10. **Admin: Health — OPEN — 1.902 s.**
11. **Admin: Overview — OPEN — 1.355 s.**
12. **Admin: Data — OPEN — 1.238 s.**
13. **Computers — OPEN — 1.195 s.**
14. **Admin: Jobs — OPEN — 1.105 s.**
15. **Admin: Settings — OPEN — 0.147 s.**

## Next action

Push approved permanent Software recovery/readiness .26 including 0420/0421;
observe rollout and protected availability, no tests/timing pass. [Scope](../records/PLAN-056-software-emergency-2026-11-17.md).
Coverage .25 latency and broader acceptance remain open.

## Follow-up — reassess Home information after domain readers

Backlog: Operations TODO, "PLAN-056 Home information restoration."
Reuse existing outputs first.

- [ ] **Source Records:** Inventory-owned total, latest report and 30-day net
  change without request-time inventory/history scans.
- [ ] **Issues:** Owned independent-action totals (open/paused/critical) and
  categories; preserve deduplication and coverage.
- [ ] **Mapping alert:** Issues-owned critical actions, affected clients and
  scoped links; no raw finding-count substitution.
- [ ] **Attention queue:** Issues-owned ranked actions, bounded affected counts
  and links, consistent with Issues filters/ranking.
- [ ] **Navigation badges, all pages:** Shared Issues/Patching queries removed
  locally. Consider returning via domain readers with exact populations, access,
  freshness metadata and a cheap cache-miss path.
- [ ] **Software detail:** Assess published decision/risk/issue breakdowns;
  distinguish installed-title status, high-risk safety titles and Home's former
  active-risk-finding population. Reuse only matching definitions.
- [ ] **Already-returned details:** Client trend, Patching activity/outcomes,
  Software breakdowns and Sources/Jobs timestamps/status; audit before new readers.

Record restore/omit/defer, population, owner/reader, access, maintenance/expiry
and unavailable behavior. Require R1–R9 and full Home latency acceptance.
