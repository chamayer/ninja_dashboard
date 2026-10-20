# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, and close PLAN-001 only with current deployed evidence.

## Scope

Measured server/rendering causes on Dashboard navigation and its landing pages. Preserve tenant/RLS, card meanings, URLs, and established data authorities. No cache, duplicate projection, speculative index, migration, or production-data action.

## Status and evidence

Active. Before release, fresh authenticated tenant-1 handler timings found Dashboard 3.154 s, Computers 12.871 s, Sources 4.474 s, Cleanup 5.368 s, User exposure 5.877 s, and Software Overview/Products over the 20 s request limit. Release 0.128.1 is healthy and contains the committed reads; Dashboard warmed to 1.308–1.568 s (first sample 3.338 s). Release 0.128.2 is healthy but Software remained slow: safety aggregation is 15 ms, the 500-title base read is 85 ms, and the redundant per-title publisher lookup timed out at 5 s. The title current read model already owns the exact most-common-publisher rule. JIT was not causal.

## Change and measurement plan

Release 0.128.4 made the Overview meet the warm target at 1.042–1.068 s (first request 12.284 s). Products remains 2.853–2.976 s warm. Its trace attributes 1.295 s to a descriptive category total followed by a second 92 ms breakdown scan; release 0.128.5 combines those exact aggregates with grouping sets. After the automatic rollout, remeasure Products, then trace only routes still outside the archive criteria before selecting another change.

## Validation

Focused pytest: 31 passed. `manage.py check`, `compileall`, registry validation, and diff whitespace checks passed for 0.128.1; the focused suite and checks also pass for 0.128.2–0.128.5. Python 3.14 reports existing Django deprecation warnings; file-wide Ruff has existing unrelated legacy findings. No schema or data changes are included.

## Checkpoint and next action

User approved the commit and pushes needed to complete the goal; `origin` automatically deploys, with no separate redeploy. Commit this scoped 0.128.5 change, push `origin` then `a-m-rose`, and perform read-only rollout and performance validation. PLAN-001 stays active until those measurements meet the archived success criteria or documented measured exceptions receive a follow-up decision.
