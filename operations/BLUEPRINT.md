# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-056 — Platform performance recovery

**Goal:** Fix Software item 1 end to end in production under ADR-0058 and the
[six-step worklist](../docs/records/PLAN-056-software-implementation-requirements.md).
User forbids scope expansion. All 15 items remain open; navigation routing:
[cross-service handoff](../docs/plans/PLAN-056-platform-performance-assessment.md).

**Deployed checkpoint:** ff63104a / 0.144.13 on both remotes, all four services
healthy, runtime files verified, 0407–0411 applied. Existing superuser limitation
retained; no role redesign. Unrelated work is uncommitted. Details and prior
corrections: [release evidence](../docs/records/PLAN-056-release-0.144.12.md).

**Current activation:** Local 0412 plus prepared-reader switch, not deployed.
Actual production snapshot comparison passed all 15 context fields including
nested metrics, using runtime app reads and a rolled-back owner calculation;
no values exposed. 0412 bodies and all snapshots passed actual DB validation
in a rolled-back transaction. No activation SQL applied.

**Bounded correction:** Use local publication owners and existing reclassification
targets/ownership dirtiness, not raw collector attempt status. Preserve explicit
actor invalidation while ignoring future dependency-only queues. Overview is
admitted on successful owner completion using existing conditional workflows
(software_inputs_ready). v4 separates it from the old dependency backlog.
0412 promotes reviewed fenced generations; HTML selects protected reader.
Products/CSV retained; no new store/service/role/cadence or collector changes.

**Next:** User directed stopping additional tests and finishing activation.
0.144.14 candidate: 0412, completion-only overview admission and protected HTML
reader. Production parity and rollback-only DB registration/SQL checks passed.
No more test expansion; package exact changes, obtain separate commit/push+0412
approvals, deploy, request one incremental classification/overview and measure
the completed page. Remote temporary publisher/parity scripts need cleanup.
Preserve unrelated Home/test edits; no new service/store/role/cadence.

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
