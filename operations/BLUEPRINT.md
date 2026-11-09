# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-044 — Navigation and Computers performance

**Goal:** Get ordinary Home response time to ≤1.5 seconds (2.0 seconds hard
maximum), preserving the agreed domain-owned overview, supported trends,
Coverage totals, and Clients portfolio boundary. No schema changes.
**Checkpoint:** `9fab308d` is pushed to both remotes and deployed; startup
reported no pending migrations and Operations is healthy. The bounded
authenticated Home request still exceeded five seconds; its database statement
was canceled. Read-only EXPLAIN estimates 63,144 selected rows. Active
source-record findings repeat 5,071 records across 13,327 findings. The local
Home-only follow-up computes source-record client attribution once per distinct
eligible record; regular Issues selections are unchanged. Python compilation,
plan-registry validation, and whitespace checks pass; local Ruff is unavailable.
**Next:** complete review, commit/push this focused follow-up, then time one
bounded ordinary Home request. See the
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
