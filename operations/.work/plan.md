# Active Operations implementation plan

Track: **Corrective Track B — stable observation identity dual-write**

**Status:** RELEASE CANDIDATE LOCALLY VALIDATED — the additive expand/backfill
release is deployed through `0.99.0` / `edc1e16`; release `0.99.1` implements
dual-write while ADR-0007 remains the sole read/write authority. No schema
migration or design change is included.

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

## Steps

1. **Complete:** reconcile the previous checkpoint with Git and production.
   Both remotes and Portainer deploy `edc1e16`; migration `0095` is applied.
2. **Complete:** verify aggregate backfill coverage and service health.
3. **Complete:** implement connector-owned namespace emission and shared
   current/history/run dual writes, including compatibility writers.
4. **Complete:** run syntax, Ruff, Django, targeted unit/PostgreSQL, migration
   state, packaging, and diff validation; review every changed hunk.
5. **In progress:** prepare one logical release commit and deploy under the user's
   standing build/commit/push authorization if no new migration or design
   decision appears.
6. **Pending:** verify commit, health/readiness, migrations, zero HTTP 500s,
   post-deployment shadow completeness/mapping/collisions, and mirror parity.

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

Local validation: changed-file Ruff passes; the two new test files pass Ruff
format checks; Python compilation, Django system check, and Django migration
state checks pass. The combined ingest/Operations suite passes 72 tests with
5 expected environment-gated skips. The focused disposable PostgreSQL 16 run
passes 19 tests, including the real dual-write current/history/run SQL. Docker
build again reaches dependency installation but is blocked by the known local
PyPI certificate-chain failure before application packaging; both Dockerfiles
do copy the changed runtime directories. `git diff --check` passes.

## Next action

Stage only the dual-write release files, review the cached diff, commit one
logical `0.99.1` change, then push/deploy and perform aggregate shadow/health
comparison before mirroring.
