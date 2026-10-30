# Root development blueprint

## Status

Registry-active plans are routed below. Plan status and lifecycle dates
are authoritative in `docs/records/PLAN_REGISTRY.md`.

## Goal

Provide one compact entry point to each active plan's current next action and
authoritative details.

## Scope

This file is only the cross-service index. `docs/records/PLAN_REGISTRY.md`
owns plan status and lifecycle dates. Module blueprints own module checkpoints;
`docs/plans/` owns cross-service plan detail. Do not store plan narratives,
validation results, or completed-plan summaries here.

## Next action — active plan routing

- **PLAN-004 — active; R4 Stages A, C and B released 2026-10-30 (0.135.0–0.137.0).**
  Next: review the one-time reassessment's changed/ambiguous/unmatched rows and the
  R4 follow-ups in `operations/TODO.md`; watch ingest timings (R4-2 waiver). See the
  [Operations handoff](operations/BLUEPRINT.md#r4-implementation-started-2026-10-30-branch-plan003-r3-base-7a8b67b)
  and [final design](operations/docs/plans/PLAN-004-source-record-final-design.md).

- **PLAN-003 — active.** R1–R3 released; R4 (PLAN-004) released 2026-10-30 (0.135.0–0.137.0).
  Next: final acceptance testing of R0–R4 (user, after the plan).

- **PLAN-026 — active, approval-gated.** PLAN-025 is complete; next obtain
  explicit approval to implement the source configuration UI using its
  documented source/binding contract. See the
  [plan](docs/plans/PLAN-026-source-configuration-ui.md).

- **PLAN-029 — active.** Next: renew scheduler heartbeat independently of
  scheduled work and collect Ninja reference data before devices. See the
  [plan](docs/plans/PLAN-029-jobs-readiness-and-first-ingest.md).

- **PLAN-007 — active.** Next: verify current implementation and migration
  `0335` against the [registry entry](docs/records/PLAN_REGISTRY.md#plan-007-ingest-domain-separation) before resuming.
- **PLAN-012 — active, gated.** Next: reconstruct and confirm the missing
  consumer ledger, design, affected-file inventory, and resumable slices in
  the [checkpoint](docs/records/PLAN-012-computer-read-checkpoint.md).
- **PLAN-015 — active.** Next: implement and validate the read-only preview;
  production reads require separate authorization. See the [plan](operations/docs/plans/PLAN-015-identity-reconciliation.md)
  and [Operations checkpoint](operations/BLUEPRINT.md).
- **PLAN-016 — active.** Next: implement the bounded, tenant-scoped,
  read-only explorer and focused tests. See the [plan](operations/docs/plans/PLAN-016-admin-sql-explorer.md)
  and [Operations checkpoint](operations/BLUEPRINT.md).
- **PLAN-019 — active, approval-gated.** Step 3 is next; each step requires
  separate explicit approval. See the [plan](docs/plans/PLAN-019-data-pipeline-correctness-and-retention.md).
- **PLAN-022 — active.** Wave A is complete. Design each Wave B item and obtain
  its separate approval before execution. See the [plan](docs/plans/PLAN-022-legacy-data-cleanup.md).

Completed and ready plans remain in the registry; their details stay in their
registered source documents. Update this index only when active status,
next action, or cross-service routing changes.
