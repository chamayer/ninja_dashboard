# PLAN-014 — Requirement and lifecycle reconciliation

## Status, goal and scope

Active; release 0.129.4 is approved for a scoped commit and push, including
migration 0357 and automatic origin deployment. Baseline `0af8aac` is deployed;
both remotes matched it when checked. Preserve unrelated work. Keep PLAN-014
open until deployed acceptance records zero unexplained drift.

Goal: reconcile lifecycle, stored requirement verdicts, findings, recovery and
honest audit explanations without deleting retained history or bypassing guards.
PLAN-014 precedes PLAN-003's overlapping persistence redesign. PLAN-012 keeps
inventory readers; identity policy stays with PLAN-004/015/021.

## Decisions and affected files

- ADR-0047 retains explicit confirmed-use checking and one shared lifecycle
  result. Registered fallback now permits recognized state for remote-access
  and monitoring agents only when no source supplies qualified direct contact.
  Existing hybrid/VM modes remain unchanged. Collection time is never contact.
- Negative fallback has unknown duration: no inferred contact-aging cleanup or
  new extended-offline root; preserve existing roots until positive recovery.
  Requirement guards explicitly say `offline:reported_without_duration`.
- Summary recognizes qualified current cleanup cover without changing raw drift.
  Migration 0357 extends the existing registry constraint/choices and audits
  only two type updates; it refuses unexpected policy and has reverse SQL.
- Affected: evaluator, requirement-state diagnostics, EntityType choices,
  migration 0357, focused ingest tests, ADR-0010/0011/0047, design, evidence and
  registry. Docker directory copies include all runtime files. No dependency,
  Compose, entrypoint, port or release-metadata change.

## Confirmed checkpoint and validation

Read-only tenant-1 evidence: 109 distinct disagreements across 114 findings,
matching recorded drift. No missing/stale-without-finding remains. The candidate
summary explains 64 entries and leaves 45 lacking registered contact evidence.
Those 45 affect 20 Computers: 12 ScreenConnect and eight R-U-ON. The read-only
fallback preview qualifies all 45 (30 associated with online state, 15 with
offline state of unknown duration). Across the fleet, 102 Computers gain state:
62 online and 40 offline; qualified-contact Computers are unchanged. This is a
preview, not proof of production reconciliation.

Final ingest batch: 135 passed on synthetic PostgreSQL 16 with real assessment,
verdict and cover functions, runtime roles, repeat runs, full/single scope,
retirement/source guards, migration reversal/precondition and snapshot/lock
rollback. Final PostgreSQL batch used JIT off for disposable test execution.
Operations: 43 coverage/migration tests pass. Django checks, migration-state
consistency and focused Ruff pass. Full-stack/browser, stress and production
candidate acceptance remain unverified. See the evidence record for earlier
fixture failures, exact limits and remaining governance checks.

## Next action

Current checkpoint: release files include VERSION/CHANGELOG; stage only PLAN-014
hunks in the shared registry. Commit the scoped files and push origin, then the
mirror. Origin push triggers deployment; no separate redeploy. Recommend a fresh
session for post-deployment verification of both runtimes, migration 0357 and
current evaluation/drift. Obtain separate approval for recalculation if needed.
Require zero unexplained drift before closing; preserve uncertainty and history.

Authorities: [design](../docs/plans/PLAN-014-requirement-reconciliation.md),
[current acceptance](../docs/records/PLAN-014-acceptance-2026-10-27.md),
[baseline build](../docs/records/PLAN-014-build-2026-10-27.md).
