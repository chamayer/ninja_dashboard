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
**Checkpoint:** `e9439cc5` is the confirmed baseline; migration 0406 is
applied. Source assessment refreshes recorded client IDs, including retained
unknown findings; mapping changes enqueue reassessment, so IDs can lag. Home
Issues uses recorded IDs and reuses its open count for navigation. Shared
source-group attention rows and critical totals match their filtered Issues scopes
while the overall action total remains deduplicated. Patching
counts all current Computers and narrows owned activity/outcomes. Inventory uses
an existence check for history. Software groups publisher counts before selecting
a title's modal publisher; its label no longer claims unproven approvals. No new
schema is proposed. PLAN-049 must use migration 0407 or later.
**Validation:** 55 existing source-record/Home/navigation tests and Django check
pass. Synthetic PostgreSQL checks cover Issues selection parity, attribution,
Patching activity/outcomes, Inventory history, Software title/publisher/risk
parity, publication status/snooze, covered representatives, Home/drilldown and
differing-severity counts,
RLS, and client-scoped source evidence. A real Home template/context smoke check confirms navigation
reuse and card labels; cold fallback and both batch-helper
PostgreSQL checks pass. No latency improvement has been measured. The old Issues fixture lacks issue_category; an
existing Home attribution assertion expects the superseded batch query and fails.
The user requested no further testing. Runtime files are included by Docker.
Whole-file formatting/lint checks report existing violations outside this change.
**Next:** Review the implementation and remaining gates in the
[acceptance evidence](docs/plans/PLAN-044-page-performance.md#acceptance-evidence-and-remaining-gates).
Respect the request to stop further testing. Full-request timing, commit, and
deployment require the applicable authorization.

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
