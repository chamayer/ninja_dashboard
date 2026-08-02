# Active Operations implementation plan

Track: **Corrective Track B — stable observation identity dual-write**

**Status:** VALIDATION REPAIR LOCALLY VALIDATED — dual-write release `0.99.1` /
`5760cd6` is deployed on `origin` but not mirrored. Production validation
exposed the pre-existing per-heartbeat advisory-lock scaling defect; `0.99.2`
contains the correctness-preserving repair. No schema migration or identity
cutover is included.

## Goal

Populate the ADR-0009 shadow identity and snapshot-run fields on every current
writer, prove that new production writes remain complete and collision-free,
and stop before stable-key cutover or reconciliation redesign.

## Scope

- Make each connector declare its stable record and container namespaces.
- Dual-write source instance, last-seen binding, namespace, parent scope, and
  external ID into observation current/history rows.
- Dual-write source instance, run start, and explicit complete-snapshot state
  into snapshot runs.
- Keep legacy identity locks, conflict targets, history lookup, snapshot
  membership pointer, reconciliation scope, constraints, readers, and derived
  consumers authoritative.
- Keep compatibility seed/backfill writers from creating empty shadow fields.
- Add focused tests and perform aggregate-only production comparison after
  deployment and at least one post-deployment collection.

Out of scope: new schema, stable-key uniqueness, per-run membership tables,
read or write cutover, overlapping-run findings, legacy-column removal,
historical deletion, Agent Compliance, and ADR-0010 ecosystem implementation.

## Affected files

- `ingest/observations.py`
- `ingest/observation_runs.py`
- `ingest/core/devices.py`
- `ingest/source_observations.py`
- Current connector modules under `ingest/connectors/`
- `ingest/backfill_observations.py`
- Observation seed commands and focused ingest tests
- Root release authorities when the slice is release-ready

## Decisions

- Connector output owns namespace selection; the shared writer validates and
  persists supplied identity components but does not infer vendor namespaces.
- The binding-to-instance relationship is resolved by the database when a run
  begins, so stale process configuration cannot write a mismatched instance.
- Top-level parents normalize to two empty strings. A partially populated
  parent scope fails closed before any current/history mutation.
- A successful partial source run records `is_complete_snapshot = false`; only
  a successful full source run records true. Reconciliation remains on the
  deployed ADR-0007 path and is still skipped for partial sources.
- This slice adds no constraint or cutover. Shadow comparison is a deployment
  gate for the later membership/cutover slice, not authority by itself.
- Existing identities serialize on their row locks. Only an absent identity
  takes the ADR-0007 per-tuple advisory lock and re-reads under it, preserving
  the new-row race guarantee without exhausting shared locks on heartbeats.

## Steps

1. **Complete:** reconcile the previous checkpoint with Git and production.
   Both remotes and Portainer deploy `edc1e16`; migration `0095` is applied.
2. **Complete:** verify aggregate backfill coverage and service health.
3. **Complete:** implement connector-owned namespace emission and shared
   current/history/run dual writes, including compatibility writers.
4. **Complete:** run syntax, Ruff, Django, targeted unit/PostgreSQL, migration
   state, packaging, and diff validation; review every changed hunk.
5. **Complete:** commit `5760cd6`, push it to `origin`, and verify deployment,
   health/readiness, migration state, and the first three source paths.
6. **Complete:** diagnose Ninja/Hudu validation failure as shared-lock
   exhaustion from retaining one advisory lock per steady-state row.
7. **In progress:** release the row-lock/advisory-lock repair as `0.99.2`,
   rerun Ninja then Hudu sequentially, finish aggregate shadow comparison,
   and mirror only the verified repair commit.

## Validation plan

- Unit tests cover required identity parts, parent-pair normalization, the
  accepted namespace map, current/history dual-write shaping, and complete
  versus partial snapshot-run bookkeeping; connector emission is also checked
  in the changed-source review.
- Existing observation, lifecycle, resolver, retention, and Operations tests
  remain green.
- `python -m py_compile`, changed-file Ruff/format checks, `manage.py check`,
  `makemigrations --check --dry-run`, Docker build where the workstation trust
  chain permits it, and `git diff --check`.
- Production checks use only the documented helper and return aggregate counts
  or service metadata—never payloads, external IDs, hostnames, clients, or
  customer records.

## Checkpoint

Release `0.99.0` / `edc1e16` was pushed first to `origin`, automatically
deployed by Portainer, then pushed to `a-m-rose`. Operations, ingest, and
Postgres are healthy; Operations `/healthz`, ingest `/healthz`, and ingest
`/readyz` pass. Django reports migration `0095` applied and Operations logged
zero HTTP 500s during the deployment window.

The first aggregate production comparison found 24,291 current rows, 38,913
history rows, and 617 snapshot runs. Missing source instances, last-seen
bindings, namespaces, external IDs, run starts, and completeness flags were
all zero. Binding-to-instance/run mismatches were zero, as were active-current
and open-history stable-key collision groups. No customer-level data was
returned. Unrelated dirty plans, docs, backlog work, probes, and the untracked
ADR-0010 draft remain preserved.

The dual-write implementation makes all five current connector paths emit
their accepted record/container namespaces, makes the database resolve a
run's source instance from its binding, validates required identity parts and
parent pairing before writes, and updates compatibility seed/backfill paths.
The legacy advisory lock, `ON CONFLICT` target, current/history lookup,
reconciliation, constraints, and consumers are unchanged.

Release `0.99.1` / `5760cd6` deployed successfully to `origin`; the recreated
containers, health/readiness endpoints, and migration state were healthy, with
zero Operations HTTP 500s. Startup collections produced 8,317 current writes,
7 material-history writes, and 3 explicitly complete runs across SentinelOne,
ScreenConnect, and LogMeIn. Missing shadow fields, binding/instance mismatches,
and current/open-history stable-key collisions were all zero.

The separately queued Ninja and Hudu validation runs returned no queue-level
error but created no snapshot boundary. Aggregate-safe log inspection found
both had rolled back with PostgreSQL shared-lock exhaustion. The cause was the
deployed ADR-0007 implementation taking and retaining an advisory lock for
every heartbeat, magnified by running both large sources concurrently. No
partial observation/run transaction committed. The mirror remains at verified
`edc1e16` while the repair is validated.

Local validation: changed-file Ruff passes; the two new test files pass Ruff
format checks; Python compilation, Django system check, and Django migration
state checks pass. The repaired combined ingest/Operations suite passes 74
tests with 5 expected environment-gated skips. The focused disposable
PostgreSQL 16 run passes the real dual-write current/history/run SQL. Docker
build again reaches dependency installation but is blocked by the known local
PyPI certificate-chain failure before application packaging; both Dockerfiles
do copy the changed runtime directories. `git diff --check` passes.

## Next action

Stage only the `0.99.2` lock-scaling repair and its decision/plan/release
updates, commit and deploy it, then rerun Ninja and Hudu sequentially and
finish aggregate verification before advancing the mirror.
