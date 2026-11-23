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

- **PLAN-056 — active, platform performance recovery.** Next: assess maintained Coverage availability/concurrency and remaining filter gates before cutover. Publication succeeded; reader disabled. See the [handoff](docs/plans/PLAN-056-platform-performance-assessment.md) and [Operations checkpoint](operations/BLUEPRINT.md).

- **PLAN-026 — active, approval-gated.** PLAN-025 is complete; next obtain
  explicit approval to implement the source configuration UI using its
  documented source/binding contract. See the
  [plan](docs/plans/PLAN-026-source-configuration-ui.md).

- **PLAN-029 — active.** Next: renew scheduler heartbeat independently of
  scheduled work. Ninja reference data now loads before devices (0.142.0). See the
  [plan](docs/plans/PLAN-029-jobs-readiness-and-first-ingest.md).

- **PLAN-037 — active.** Steps 1–3 done; Step 5 failures have stopped. Step 4
  (deploy-interrupted runs) is implemented locally; ship it with the next
  approved release and verify after a deploy. See the
  [plan](docs/plans/PLAN-037-source-failures.md).
- **PLAN-015 — active.** Next: verify the Ninja fix rollout, then resume Milestone 4.
  See the [Operations checkpoint](operations/BLUEPRINT.md).
- **PLAN-016 — active.** Next: implement the bounded, tenant-scoped,
  read-only explorer and focused tests. See the [plan](operations/docs/plans/PLAN-016-admin-sql-explorer.md)
  and [Operations checkpoint](operations/BLUEPRINT.md).

Completed and ready plans remain in the registry; their details stay in their
registered source documents. Update this index only when active status,
next action, or cross-service routing changes.
