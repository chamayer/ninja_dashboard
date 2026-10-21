# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, and close PLAN-001 only with current deployed evidence.

## Scope

Measured server/rendering causes on Dashboard navigation and its landing pages. Preserve tenant/RLS, card meanings, URLs, and established data authorities. No cache, duplicate projection, speculative index, migration, or production-data action.

## Status and evidence

Active. Before release, fresh authenticated tenant-1 handler timings found Dashboard 3.154 s, Computers 12.871 s, Sources 4.474 s, Cleanup 5.368 s, User exposure 5.877 s, and Software Overview/Products over the 20 s request limit. Release 0.128.1 is healthy and contains the committed reads; Dashboard warmed to 1.308–1.568 s (first sample 3.338 s). Release 0.128.2 is healthy but Software remained slow: safety aggregation is 15 ms, the 500-title base read is 85 ms, and the redundant per-title publisher lookup timed out at 5 s. The title current read model already owns the exact most-common-publisher rule. JIT was not causal.

## Change and measurement plan

Release 0.128.8 improved User exposure to 2.917–2.933 s warm. Sources trace attributes 1.114 s to a legacy-history transfer; a per-binding latest-terminal/latest-success query takes 82 ms with identical fallback inputs. Release 0.128.9 applies that bounded read. After rollout, remeasure Sources, User exposure, Computers, and Products, then trace only routes still outside the archive criteria.

## Validation

Focused pytest: 32 software tests, 14 coverage tests, and two User exposure tests passed. `manage.py check`, `compileall`, registry validation, and diff whitespace checks passed. Python 3.14 reports existing Django deprecation warnings; file-wide Ruff has existing unrelated legacy findings. No schema or data changes are included.

## Checkpoint and next action

User approved the commit and pushes needed to complete the goal; `origin` automatically deploys, with no separate redeploy. Commit this scoped 0.128.9 change, push `origin` then `a-m-rose`, and perform read-only rollout and performance validation. PLAN-001 stays active until the archived success criteria are verified.
