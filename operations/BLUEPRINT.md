# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-043 — Useful issue review

**Goal:** Explain the detected issue, show relevant safe evidence, and present
existing resolution paths on the review page, including native source-record
identity findings.
**Scope/files:** `apps/core/finding_review.py`, `apps/core/views.py`,
`templates/finding_review.html`, focused tests, and plan/checkpoint documents.
No schema, identity-policy or source-data change. Release 0.143.2 commit and push
approved 2026-11-02; pre-push review found no pending Django or ingest migrations.
**Decisions:** Reuse safe source metadata and existing action permissions/handlers.
Distinguish the evidence recorded at detection from current source attachments.
Do not manufacture a merge/move action for an issue with no registered action.
**Steps:** Inspect producer and action contracts; build bounded review context;
render explanation/comparison/actions; run synthetic request/template checks.
**Validation:** 14 new checks pass; the focused run has 49 passing tests and one
pre-existing source-text assertion failure, also confirmed against HEAD. Django
system checks, focused lint/format, registry, and whitespace pass. A staged,
read-only render of the linked finding succeeds (2 Computers, 4 source records).
**Checkpoint:** Local implementation complete; safe native comparisons, explicit
current/detection roles, handling steps, existing authorized action forms, and
source-record/case destinations are wired. No live UI deployment or browser check.
**Next:** Commit the scoped release, push origin then the mirror, and inspect
automatic deployment; no separate redeploy.
Detailed scope/evidence: [plan](docs/plans/PLAN-043-issue-review.md).

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
