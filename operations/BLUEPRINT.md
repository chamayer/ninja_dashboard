# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-044 — Navigation and Computers performance

**Goal:** Ordinary Home ≤1.5 seconds; hard maximum under 2 seconds. Preserve
the agreed domain KPIs, supported trends, known-client impact counts, and
Clients portfolio boundary.
**Scope/files:** Home/Issues/navigation readers and template, source-record
finding publication, Patching, Software, and Inventory owner readers. Exact
files, ordered steps, decisions, and acceptance checks are in the
[current implementation plan](docs/plans/PLAN-044-page-performance.md#home-implementation-plan--2026-11-09-review).
**Checkpoint:** `60ba6e45` is on both remotes. An authenticated Home request
took 14.440 seconds; Patching's query took 6.814 seconds. The detailed
[plan](docs/plans/PLAN-044-page-performance.md#acceptance-evidence-and-remaining-gates)
records earlier evidence and limitations. The user authorized implementing the
Patching summary only. Preserve current ownership, scope and exact rolling
30-day semantics; make summary updates reflect committed patch facts.
SQL migration 119 and the Home reader now maintain and use exact-timestamp
outcome counts. Synthetic PostgreSQL mutation parity, Python compilation,
registry validation and whitespace checks passed. Production speedup, storage,
write overhead, and migration-lock duration are unmeasured; startup fallback
handles independent service ordering. Details and deployment risks are in the plan.
**Next:** Commit the reviewed change as authorized, then obtain push approval
explicitly covering migration 119 and automatic deployment.

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
