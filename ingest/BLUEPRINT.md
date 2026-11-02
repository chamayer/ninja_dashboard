# PLAN-014 — Requirement and lifecycle reconciliation

## Status, goal and scope

Complete; commit `79088db` (0.129.4, migration 0357) is deployed on origin and
the mirror. Read-only production verification confirmed healthy service
containers, migration 0357 applied, deployed files matching the commit, and
zero unexplained drift. See the [acceptance record](../docs/records/PLAN-014-acceptance-2026-10-27.md).

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

Read-only tenant-1 evidence (2026-10-28): 79 distinct disagreements match
recorded drift; all are retained by current guards, with zero requiring review
and zero other disagreement types. The latest platform evaluation succeeded.
Current covered findings have active same-tenant/same-subject parents, and the
100 actionable unknown-OS findings remain within the original estimate.

Final ingest batch: 135 passed on synthetic PostgreSQL 16 with real assessment,
verdict and cover functions, runtime roles, repeat runs, full/single scope,
retirement/source guards, migration reversal/precondition and snapshot/lock
rollback. Final PostgreSQL batch used JIT off for disposable test execution.
Operations: 43 coverage/migration tests pass. Django checks, migration-state
consistency and focused Ruff pass. Production acceptance is verified. Full-stack
browser behavior, stress tests and a representative synthetic full-fleet
performance benchmark remain unverified. See the evidence record for earlier
fixture failures, exact limits and remaining governance checks.

## Next action

Current checkpoint: commit `79088db` is on both remotes; origin deployment is
verified. Read-only checks confirmed healthy runtimes, applied migration 0357,
current successful evaluation and zero unexplained drift. No recalculation was
triggered. PLAN-014 is complete; preserve uncertainty and history. Remaining
browser, stress and performance checks are outside this plan's completed
production acceptance gate.

Authorities: [design](../docs/plans/PLAN-014-requirement-reconciliation.md),
[current acceptance](../docs/records/PLAN-014-acceptance-2026-10-27.md),
[baseline build](../docs/records/PLAN-014-build-2026-10-27.md).
