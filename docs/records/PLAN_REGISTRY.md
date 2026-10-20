# Plan registry

This is the repository authority for the status of substantial work. Archive
files preserve their detailed reasoning and evidence; they are current only
when an entry below names them. `BLUEPRINT.md` is required only while an
`active` plan is being executed.

Statuses: `active` (executing under a blueprint), `ready` (resumable after its
gate), `verify` (preserved but needs current corroboration), `deferred`,
`completed`, `superseded`, and `archived-only`.

Multiple plans may be `active` when their scopes are independent. Each active
plan must name its own blueprint. Plans with overlapping scopes must name the
other plan and state their dependency or execution order in their resume gate;
do not open competing blueprints for the same work.

## PLAN-001 — Dashboard navigation performance

- Scope: Root and Operations performance
- Status: active
- Defined: 2026-10-13
- Started: 2026-10-13
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Dashboard navigation performance
- Resume gate: Release 0.128.4, then repeat authenticated handler and browser/navigation measurements. Do not close until the archived success criteria or measured, explicitly deferred exceptions are recorded.
- Last checked: 2026-10-20 (releases 0.128.1–0.128.3 are healthy; their current handler evidence and the scoped 0.128.4 follow-up are recorded in `BLUEPRINT.md`).

## PLAN-002 — Source-driven collection and Jobs recovery

- Scope: Cross-service collection and Jobs
- Status: verify
- Defined: 2026-10-08
- Started: 2026-10-08
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — source-driven collection
- Resume gate: Reconcile the October recovery checkpoint with current Jobs code, decisions, and deployed evidence.
- Last checked: 2026-10-20 (live). Six source bindings are enabled/scheduled; R-U-ON, Hudu, ScreenConnect, LogMeIn, and SentinelOne had no failed runs in seven days, while Ninja had 39 failed runs of 167.

## PLAN-003 — Central work queue and finding state

- Scope: Operations findings workflow
- Status: verify
- Defined: 2026-10-14
- Started: 2026-10-15
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Central work queue (design awaiting approval)
- Resume gate: Compare the remaining W7-W9 items with current finding-state decisions and releases before reopening implementation.
- Last checked: 2026-10-20 (live). Evaluator, patch-finding, and software-classifier runs had no failures in seven days; the current finding population is 37,885 open and 548,617 resolved, so workstream completeness is not established by health alone.

## PLAN-004 — Computer identity, history, and naming

- Scope: Operations identity lifecycle
- Status: verify
- Defined: 2026-10-16
- Started: 2026-10-16
- Completed: —
- Blueprint: —
- Source: operations/docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Computer identity and platform change history (2026-10-16); How a Computer is named — ADR-0034 proposal (2026-10-19)
- Resume gate: Reconcile post-ADR-0034 follow-ups against the 0.128.0 release and current ADRs.
- Last checked: 2026-10-20 (live). Identity relations are present; 32 merges occurred in seven days and seven name collisions remain. This confirms activity, not completion of the follow-up plan.

## PLAN-005 — Jobs observability and schedule authority

- Scope: Operations Jobs
- Status: verify
- Defined: 2026-10-19
- Started: 2026-10-19
- Completed: —
- Blueprint: —
- Source: operations/docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Jobs observability and maintenance cadence (2026-10-19); Schedule retirement authority (2026-10-19)
- Resume gate: Verify the remaining health/schedule follow-ups against current Jobs behavior before treating them as open work.
- Last checked: 2026-10-20 (live). All 24 enabled schedules have no overdue next run; durable Jobs had 4,117 completed, 109 failed, and 38 stalled runs in seven days, so the plan remains unresolved.

## PLAN-006 — Legacy agent-compliance retirement

- Scope: Root and Operations platform cleanup
- Status: deferred
- Defined: 2026-10-13
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/backlog.md
- Section: Legacy agent-compliance cutover
- Resume gate: Approve a compatibility and data-retention plan before destructive retirement work.

## PLAN-007 — Ingest domain separation

- Scope: Ingest architecture
- Status: deferred
- Defined: 2026-06-19
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/backlog.md
- Section: Ingest domain separation
- Resume gate: Approve extraction of shared scheduler/bootstrap ownership.

## PLAN-008 — Metabase retirement

- Scope: Retired reporting runtime
- Status: completed
- Defined: 2026-10-12
- Started: 2026-10-12
- Completed: 2026-10-12
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Completed plan — Metabase retirement
- Resume gate: No action; any rollback or archive destruction requires a new approved plan.
- Last checked: 2026-10-20 (live). No Metabase container is running; the replacement ingest, Operations, Jobs worker, and Postgres containers are healthy.

## PLAN-009 — Plan-status governance

- Scope: Repository documentation governance
- Status: completed
- Defined: 2026-10-20
- Started: 2026-10-20
- Completed: 2026-10-20
- Blueprint: BLUEPRINT.md
- Source: docs/records/CLEANUP_SUMMARY-2026-10-20.md
- Section: Remaining intentional workspace material
- Resume gate: Complete registry/backlog validation and record the outcome in the blueprint.

## PLAN-010 — Work-status reconciliation

- Scope: Repository and Operations documentation governance
- Status: completed
- Defined: 2026-10-20
- Started: 2026-10-20
- Completed: 2026-10-20
- Blueprint: BLUEPRINT.md
- Source: docs/records/PLAN_REGISTRY.md
- Section: PLAN-010 — Work-status reconciliation
- Resume gate: No action; select a `ready` plan or perform the recorded verification gate for a `verify` plan.

## PLAN-011 — Software inventory and findings rebuild

- Scope: Operations software inventory and findings
- Status: completed
- Defined: 2026-10-13
- Started: 2026-10-13
- Completed: 2026-10-13
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Software inventory ingest rebuild; Active plan — Software findings rebuild (implementation)
- Resume gate: No action; open a new plan only for a verified follow-up not covered by the 0.127.0 release.
