# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-044 — Navigation and Computers performance

**Goal:** Get ordinary Home response time to ≤1.5 seconds (2.0 seconds hard
maximum), preserving the agreed domain-owned overview, supported trends,
Coverage totals, and Clients portfolio boundary. No schema changes.
**Checkpoint:** Commit `9f3769a9` is pushed to both remotes and deployed; startup
reported no pending migrations and Operations is healthy. PLAN-043 issue review
was already committed as `cab7e6f2`. The deployed authenticated Home request
exceeded the five-second client wait and later returned 500: `mapping_query()`
read an undefined `groups` name. The request's Issues aggregate remained active
for about 98 seconds. Production EXPLAIN estimated 63,144 rows through the
window step; Home repeated the Issues selection for counts, mapping and
attention. A combined compact read still timed out at five seconds and its
window query ran for 108 seconds; that abandoned read was canceled. The current
local revision removes global ranking from Home and deduplicates only the two
documented shared-action types, preserving their admin-first representative
and covered-item rules. The `mapping_query()` name is also fixed. Python
compilation, targeted Ruff, registry and whitespace checks pass; no tests were
run. **Next:** commit and push this revised owner query, then measure one
bounded ordinary Home GET. See the
[handoff](docs/plans/PLAN-044-page-performance.md).
See the [handoff](docs/plans/PLAN-044-page-performance.md).

## PLAN-015 — Identity reconciliation

Independent of PLAN-043's read-only display work. Registry remains active.
The retained checkpoint reports a validated preview and a guard-aware 110-candidate
follow-up; these historical counts have not been rerun for this task.
**Next:** Verify current state and review candidates before proposing repairs.
Any reattachment, merge or derived refresh needs its own approval.
See the [plan](docs/plans/PLAN-015-identity-reconciliation.md) and retained checkpoint.

## PLAN-016 — Admin SQL explorer

Independent scope; registry remains active with an approval gate. The retained
checkpoint describes planned work; no implementation is claimed here.
**Next:** Obtain implementation approval, then inspect Admin Data routing/tests.
See the [plan](docs/plans/PLAN-016-admin-sql-explorer.md).
