# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
History: [checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md); verify first.

## PLAN-056 — Platform performance recovery

**Goal:** Recover Home responsiveness and Software freshness; preserve access,
population, input/claim fences and expiry contracts.

**Deployed:** 0891738b / 0.144.26 on both remotes and production; services healthy;
0420/0421 applied. .26 latency is unmeasured. [Prior measurement](../docs/records/PLAN-056-release-0.144.24.md).
Recorded full preparation 47.93 s; reuse 14.95 s; details in linked evidence.
Full 15-page acceptance is not claimed.

**Software mechanism:** Certified reuse and unchanged-write filtering preserve
timestamps/expiry; detailed evidence is linked below.

**Validation:** Syntax/Ruff/governance passed and real publication/HTML observed.
Earlier readiness memoization candidate withdrawn; later Home .23 now deployed.
Detailed history and limitations remain in linked records.

**Checkpoint/next:** Patching candidate implemented locally: correlated ownership,
ordered page IDs before details, consistent counts and complete batched CSV.
Django check passes; PostgreSQL execution/speedup unverified. User now approves
commit/push: prepare .27 (no new migrations), push origin then mirror and observe
automatic rollout. Keep validation light; no separate redeploy/timing campaign.
[Implementation/evidence](../docs/records/PLAN-056-patching-reader-implementation.md).
[Page results](../docs/records/PLAN-056-page-remeasurement-2026-11-17.md).
Resume reconciled Git and live state at 18:25 UTC Nov 17:
.26 is on both remotes; changed runtime hashes match; four services healthy;
0420/0421 applied. Actual Operations reader current/completed with data.
Audited ownership replay and shared scheduler/claim readiness gate are deployed.
Freshness/claim/access fences unchanged. Diagnostic staging removed; no tests
or timing pass during that earlier resume. Sustained freshness and full-page
acceptance remain open.
[Scope/security/evidence](../docs/records/PLAN-056-software-emergency-2026-11-17.md).
Coverage .25 remains unmeasured; its evidence stays in linked records.

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
