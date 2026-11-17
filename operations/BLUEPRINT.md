# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
History: [checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md); verify first.

## PLAN-056 — Platform performance recovery

**Goal:** Recover Home responsiveness and Software freshness; preserve access,
population, input/claim fences and expiry contracts.

**Deployed:** 751badfa / 0.144.23 on both remotes and production; services healthy.
Recorded full preparation 47.93 s; reuse 14.95 s; details in linked evidence.
Full 15-page acceptance is not claimed.

**Software mechanism:** Certified reuse and unchanged-write filtering preserve
timestamps/expiry; detailed evidence is linked below.

**Validation:** Syntax/Ruff/governance passed and real publication/HTML observed.
Earlier readiness memoization candidate withdrawn; later Home .23 now deployed.
Detailed history and limitations remain in linked records.

**Checkpoint/next:** Emergency triage on 2026-11-17: services healthy, Software
current/populated, latest publication 46.69 s; Home HTML 10.735 s, Software
2.185 s. Home trace: 7.031 s SQL, chiefly Software 2.328 s, Source Records
2.310 s and Issues 1.381 s. No active lock blocker or sampled swap thrashing.
User authorized all-worktree reconciliation and deployment, then stopped testing.
26 focused checks passed beforehand. Conflicting cache/legacy candidates retired;
Home cheap/published counts, client evidence and records reconciled. No pending
migrations. Release .23 deployed. One-pass HTML: Home 3.647 s, Coverage 5.148 s;
latency remains open. User approved removing shared Issues/Patching navigation
badge queries across pages; implemented locally with return-to-consider follow-up.
No tests run. User then authorized a three-minute Coverage fix. Local migration
0418 adds a page-ID-aware protected Hudu reader: IDs filter inside the materialized
input; same owner, tenant/population guards and explicit grants. Coverage calls
it after pagination, with 100-ID batches also covering complete CSV selection.
Compact fleet filtering/totals remain unchanged; latency is unverified. User now approves
commit/push including 0418 and badge removal as .24, then one measurement pass.
Next: push both remotes, observe deployment and measure; no tests.
[Reader scope/security/rollback](../docs/records/PLAN-056-coverage-page-detail-reader.md).

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
