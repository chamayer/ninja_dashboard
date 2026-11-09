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
for about 98 seconds. Its production plan estimates 63,144 rows through the
wide window step; Home was separately recomputing Issues selection for open,
paused, mapping, and attention values. Current local fix restores the taxonomy
variable and makes the Issues owner return Home totals and attention from one
compact selection, preserving action deduplication, covered-item filtering,
scope and priority semantics. The Inventory read remains split at 0.80 seconds
versus 1.54 seconds with exact parity in the prior read-only snapshot. Python
compilation and targeted Ruff checks pass; no tests were run. **Next:** review,
commit and push this focused fix, then measure one bounded ordinary Home GET in
production. Continue to ≤1.5 seconds, with 2.0 seconds as the hard maximum.
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
