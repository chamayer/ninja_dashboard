# Ninja Dashboard requirements

## Purpose

Ninja Dashboard must collect operational data on a schedule, retain current and
historical state in Postgres, provide trustworthy reporting in Metabase, and
support operator workflows through the Operations application.

## Functional requirements

### Ingest platform

- Pull source data without requiring an administrator workstation or manual
  exports.
- Maintain shared source lookups and independent domain modules.
- Record run status, timing, row counts, cursors, and failures.
- Preserve raw source payloads where they are needed for later analysis.
- Support scoped refreshes and full refreshes without silently losing current
  state.

### Patching and activity reporting

- Report Windows patch population, inclusion scope, current state, installation
  outcomes, failures, reboot requirements, and trends.
- Keep MANUAL, DELAYED, APPROVED, FAILED, REJECTED, and INSTALLED semantics
  distinct.
- Use one documented formula for fully patched metrics.
- Preserve the distinction between never patched and installed rows whose
  install dates are unavailable.
- Use activity data as contextual evidence rather than substituting it for
  authoritative patch-install facts.

### Multi-source operations

- Collect and reconcile observations from Ninja and additional operational
  sources without making one source the universal platform authority.
- Maintain canonical clients and devices separately from source observations.
- Support identity review, client mapping, coverage requirements, findings,
  suppressions, notifications, software decisions, and patching scope.
- Keep customer and tenant boundaries enforceable throughout the Operations
  UI and database access.

### Operator interfaces

- Metabase provides read-oriented dashboards and exploration.
- Operations provides write-side review, decisions, configuration, findings,
  and control-plane workflows.
- Operator-facing labels must avoid leaking internal schema and condition
  identifiers.
- Filtering and drilldown must make the population and scope behind a metric
  visible.

## Nonfunctional requirements

- Run unattended in Docker Compose.
- Store durable state in Postgres.
- Remain usable when an upstream API is unavailable.
- Keep secrets and customer data outside Git.
- Preserve source fidelity while exposing normalized cross-source views.
- Make migrations idempotent or safely ordered through the documented
  migration systems.
- Avoid repository-relative runtime mounts that are unavailable in the
  production deployment model.
- Provide health endpoints and repeatable external validation.

## Compatibility requirements

- Python ingest code and the Django Operations module must remain compatible
  with their documented runtimes.
- Postgres schemas and views consumed by Metabase must not change without a
  consumer audit.
- Dashboard bootstrap code, SQL migrations, Django migrations, Dockerfiles,
  entrypoints, and Compose must be reviewed together when runtime shape changes.
- Renames require a whole-repository old-name audit.

## Acceptance criteria for a change

- The source, storage, derived view, and UI layers agree.
- Relevant tests, syntax checks, Ruff/Django checks, SQL review, or generated
  dashboard inspection pass.
- Tenant/RLS behavior remains correct for Operations changes.
- Runtime files are included in the appropriate image.
- Release-visible work updates root VERSION and CHANGELOG when an approved
  release is prepared.
