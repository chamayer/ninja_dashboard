# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
History: [checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md); verify first.

## PLAN-056 — Platform performance recovery

**Current work:** 727df0e5/.30 live; 0423 applied, worker stable after one rollout
restart; all services healthy. Coverage producer fails on five missing publisher
SELECT grants. Audited all inputs/policies; 0424/.31 prepared, needs explicit
commit/push/migration approval. Reader disabled; live 4.369 s, candidate 1.624 s.
Contract: docs/decisions/0059-coverage-maintained-selection.md.
[Scope/checkpoint](../docs/records/PLAN-056-coverage-reader-remediation.md).

**Goal:** Recover Home responsiveness and Software freshness; preserve access,
population, input/claim fences and expiry contracts.

**Deployed:** 2edf638a / 0.144.29 on both remotes and production; registry hashes
match committed blob. 0420–0422 applied. [Prior measurement](../docs/records/PLAN-056-release-0.144.24.md).
Recorded full preparation 47.93 s; reuse 14.95 s; details in linked evidence.
Full 15-page acceptance is not claimed.

**Software mechanism:** Certified reuse and unchanged-write filtering preserve
timestamps/expiry; detailed evidence is linked below.

**Validation:** Syntax/Ruff/governance passed and real publication/HTML observed.
Earlier readiness memoization candidate withdrawn; later Home .23 now deployed.
Detailed history and limitations remain in linked records.

**Checkpoint/next:** .27 full pass: all 15 returned 200; completion/logout/cleanup
confirmed. Coverage 4.214 s, Patching 1.423 s, Home 1.378 s. Software returned
pending/input_changed without summary data; 0.260 s is not populated latency.
Coverage trace: distributed SQL and fleet preparation; no single dominant query.
Remaining [attribution](../docs/records/PLAN-056-coverage-bottleneck-attribution.md)
stays open beyond the approved presence semijoin; acceptance remains open.
[Implementation/evidence](../docs/records/PLAN-056-patching-reader-implementation.md).
[Page results](../docs/records/PLAN-056-page-remeasurement-2026-11-17.md).
Prior Software recovery/security evidence remains in the
[incident record](../docs/records/PLAN-056-software-emergency-2026-11-17.md).

**Release safety:** Origin then mirror; push automatically deploys. Protect real
input handlers during rollout. Do not cancel workflow children just to change
digests. Recovery allow-list derives from Software input owners; the earlier
intel-matcher omission was corrected. Scheduler lease release confirmed. Preserve
reconciled work; no serving-file hotpatch.

**Evidence:** [Delta/validation](../docs/records/PLAN-056-software-preparation-delta.md),
[reuse](../docs/records/PLAN-056-software-preparation-reuse.md),
[capacity](../docs/records/PLAN-056-software-publication-capacity.md),
[Sources](../docs/records/PLAN-056-sources-reader-release.md),
[Source Records](../docs/records/PLAN-056-source-records-contract-check.md).
Plan lifecycle belongs to the registry; other page baselines stay open.

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
