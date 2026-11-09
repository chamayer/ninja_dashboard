# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-044 — Navigation and Computers performance

**Goal:** Get ordinary Home response time to ≤1.5 seconds (2.0 seconds hard
maximum), preserving the agreed domain-owned overview, supported trends,
Coverage totals, and Clients portfolio boundary. No schema changes.
**Checkpoint:** `599dc916` is on both remotes and deployed; Operations is
healthy. A 40-record attribution sample took 0.538 seconds; 5,071 active source
records require the same protected evidence lookup. The user authorized an
additive tenant-checked bulk security-definer function and focused tests. PLAN-044
owns migration 0406 after 0405; PLAN-049 must rebase its unmerged index to 0407
or later. Migration 0406 and Home query wiring are implemented locally; the
focused PostgreSQL tests pass. One unrelated stale source-text Issues assertion
fails on unchanged `views.py`. **Next:** review and commit the local change, then
request origin push approval including migration 0406 and automatic Portainer
deployment. See the
[handoff](docs/plans/PLAN-044-page-performance.md).

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
