# PLAN-056 — Platform performance recovery

## Goal and authority

Recover performance across Operations, ingest, Jobs, Postgres and host resources.
The [registry](../records/PLAN_REGISTRY.md) owns lifecycle status; this file owns
active execution order. Prior scope is in the
[consolidation record](../records/PLAN-056-consolidation.md).

## Scope and gates

User direction, 2026-11-11: stay on this numbered worklist until every item is
settled unless explicitly redirected. Start with item 1; preserve numbering and
baselines. Shared summary work must identify covered items and record each
outcome. Do not switch to unrelated work or a new assessment campaign.

Settled means an evidence-backed disposition accepted by the user: fixed with
relevant correctness and full-page validation, accepted as-is, or explicitly
deferred by the user. A fast sample, query improvement, HTTP 200, local test or
proposal alone does not settle an item. Do not silently drop fast pages or
renumber around unfinished ones. Record each disposition and its evidence in the
[acceptance record](../records/PLAN-056-release-acceptance.md), then update this list.

Preserve excluded working changes. No new runtime/test change, schema change,
external run, commit, push or deployment is authorized by this documentation
update. Existing separate gates apply. No local fleet/timing run, forced Job or
manual redeploy. Use domain-owned published summaries with reviewed population,
security, freshness and maintenance contracts; do not assume every slow page's
cost is aggregation or substitute a cache hit for cold acceptance.

## Current checkpoint and evidence

HEAD `ae45b463` / 0.144.11; local identity verified on resume. Deployment and
migration evidence remains in the [release record](../records/PLAN-056-release-0.144.11.md);
do not infer fresh production state from it. Excluded working changes remain
preserved and are not the deployed release.

The [acceptance record](../records/PLAN-056-release-acceptance.md) owns validation,
reader timings, hashes and cleanup evidence. Root TODO owns deferred resource
interaction. The existing assessment checklist retains broader acceptance without
superseding this worklist. Follow AGENTS.md's
automatic-deployment rule; the release record retains the runbook contradiction.

## Fixed numbered navigation worklist

Baseline: 2026-11-11, one configured-admin internal HTTP request per page;
all HTTP 200 with completion markers. Seconds cover complete HTML only, exclude
browser/external-network costs, and do not establish cold state or a new SLO.
Home retains <=1.5 s ordinary / <2 s hard maximum including cold navigation.
All items remain open; none has an accepted disposition yet.

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

Item 1: ADR-0058 accepted 2026-11-11. See the
[implementation worklist](../records/PLAN-056-software-implementation-requirements.md).
Local Software implementation and finite W1–W4 owner coverage are complete;
actual synthetic Jobs/rollback checks passed with the limitations recorded in
the acceptance record. Aggregate uncertified; page uses live reads.
Next: review the completed local change for separately authorized service
migrations, runtime-role/security and representative freshness/full-HTTP proof.
See the [Operations checkpoint](../../operations/BLUEPRINT.md).
Speculative design/SQL drafts remain set aside. Test-file edits, certification,
live build, external execution, cutover and release remain separately gated.
All 15 navigation items remain open.
