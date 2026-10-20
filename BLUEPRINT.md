# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, and close PLAN-001 only with current deployed evidence.

## Scope

Measured server/rendering causes on Dashboard navigation and its landing pages. Preserve tenant/RLS, card meanings, URLs, and established data authorities. No cache, duplicate projection, speculative index, migration, or production-data action.

## Status and evidence

Active. Before this release, fresh authenticated tenant-1 handler timings found Dashboard 3.154 s, Computers 12.871 s, Sources 4.474 s, Cleanup 5.368 s, User exposure 5.877 s, and Software Overview/Products over the 20 s request limit. Dashboard’s duplicate active-findings aggregates accounted for 2.317 s; a grouping-sets prototype took 0.771 s. Software’s unbounded safety-row transfer was the blocker; its overview aggregate took 50 ms. JIT was not causal.

## Change and measurement plan

Release 0.128.1 replaces Dashboard’s duplicate aggregates with one tenant-scoped grouping-sets read. It bounds ordinary HTML Software safety enrichment to the displayed 500 titles, retaining full filtered/CSV results and aggregate overview counts. After the automatic `origin` rollout, confirm the image contains both changes, run repeated authenticated handler timings, then run the documented authenticated browser/navigation measurement. Trace only routes still outside the archive criteria before selecting another change.

## Validation

Focused pytest: 30 passed. `manage.py check`, `compileall`, registry validation, and diff whitespace checks passed. Python 3.14 reports existing Django deprecation warnings; file-wide Ruff has existing unrelated legacy findings. No schema or data changes are included.

## Checkpoint and next action

User approved the commit and pushes needed to complete the goal; `origin` automatically deploys, with no separate redeploy. Commit this scoped 0.128.1 change, push `origin` then `a-m-rose`, and perform read-only rollout and performance validation. PLAN-001 stays active until those measurements meet the archived success criteria or documented measured exceptions receive a follow-up decision.
