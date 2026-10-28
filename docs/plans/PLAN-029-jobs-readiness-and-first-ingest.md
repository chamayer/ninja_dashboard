# PLAN-029 — Jobs readiness and first ingest

## Goal

Keep Jobs runtime health accurate when scheduled work is disabled and make
manual first-run Ninja device collection satisfy its reference-data FKs.

## Scope

- Renew the scheduler heartbeat on its normal poll even when due-schedule
  production is disabled.
- Collect Ninja organizations, locations, and policies before devices in the
  device snapshot workflow.
- Keep scheduled work disabled locally; do not trigger source or notification
  jobs during implementation.

## Affected files

- `ingest/operator_job_queue.py`
- `ingest/main.py`
- `docs/records/PLAN_REGISTRY.md`, `BLUEPRINT.md`

## Decisions and validation

Scheduler liveness is independent from whether it admits scheduled work.
Ninja reference rows are prerequisites for valid device rows, so fetch them
before device upserts. Compile changed Python, verify fresh scheduler
heartbeats and the disabled schedule gate locally, and run repository
documentation/whitespace checks. Do not rerun production-source collection.

## Checkpoint

Started 2026-10-28. Ingest and Jobs worker are running. Scheduler heartbeat is
only recorded in the enabled-schedule branch; the failed Ninja device step
referenced a missing location row. No follow-up source or notification job has
been run.

## Next action

Implement both fixes and validate scheduler liveness without admitting any
scheduled work.
