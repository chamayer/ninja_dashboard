# Ninja Dashboard architecture

> This is the root cross-module architecture authority. It describes stable
> boundaries and dependency directions, not task history. Consult it before a
> change crosses ingest, SQL, Operations, shared code, or deployment packaging.

## System overview

```text
Ninja and other sources
        │
        ▼
Operations Ingest Engine
        │ raw/source schemas + migrations
        ▼
Postgres
   └── Operations Django application
         ├── canonical entities
         ├── identity and client resolution
         ├── findings and notification workflows
         └── operator decisions
```

The repository builds custom Postgres, ingest, and Operations images.

## Repository layers

| Path | Responsibility |
|---|---|
| `ingest/` | Schedulers, source connectors, migrations, domain processing |
| `sql/init/` | First-boot database initialization |
| `sql/migrations/` | Ingest-managed SQL schema evolution |
| `operations/` | Django/DRF/HTMX operator control plane |
| `docker-compose.yml` and `*.Dockerfile` | Runtime packaging and orchestration |

## Ownership and dependency rules

- Source connectors and ingest code own acquisition, source fidelity, and
  ingest-managed schema evolution. They do not make tenant-facing operator
  decisions.
- The `operations` schema and Django application own source-agnostic canonical
  entities, tenant-safe read models, operator decisions, findings, and
  workflows.
- `shared/` may contain contracts consumed by both applications, but must not
  become a hidden third business domain.
- `sql/` contains root-level initialization and ingest migrations; Operations
  Django migrations remain under `operations/apps/*/migrations/`.
- Dependency direction is connectors/source schemas -> ingest processing ->
  persisted observations and derived state -> Operations read models and UI.
  UI actions must not write back into an external source platform.
- A cross-boundary change must name its data owner, migration owner, read/write
  contract, tenant/RLS effect, validation path, and any required ADR.

## Documentation authority

| Question | Authority |
|---|---|
| Cross-service boundaries, ownership, and deployment shape | This document |
| Root scope and acceptance criteria | `docs/requirements.md` |
| Current verified state | `docs/current-state.md` (only when its date is current) |
| Deployment/recovery procedure | `docs/operations.md` |
| Operations internals | `operations/docs/architecture.md`, then `operations/DESIGN.md` when needed |
| Settled decisions | Root or Operations `docs/decisions/` |
| Active task | Applicable `BLUEPRINT.md` |

## Source and domain schemas

- `ninja_core` stores source lookups, devices, snapshots, custom fields,
  ingest state, and run logs.
- Domain schemas such as `ninja_patches`, `ninja_activities`, and
  `ninja_inventory` own source-domain facts and derived reporting structures.
- Raw source schemas retain source terminology and fidelity.
- The `operations` schema provides source-agnostic canonical entities,
  observations, decisions, findings, and effective views.

## Ingest flow

1. Load external configuration and source credentials.
2. Apply pending ingest-managed SQL migrations.
3. Pull shared source entities.
4. Pull domain-specific facts and observations.
5. Resolve or queue client/device identity.
6. Refresh domain and Operations derived state in dependency order. This is a
   collection-completion invariant for scheduled, startup, and on-demand runs:
   a run must not report completion until the current/derived state fed by its
   collected data has refreshed successfully.
7. Evaluate findings and notification workflows when enabled.
8. Record run results and expose health/manual-run endpoints.

## Historical-state strategy

- Slowly changing source facts use content hashes and observation windows where
  state-transition history is required.
- Highly volatile device snapshots are append-oriented and retained according
  to policy.
- Raw payload columns preserve unmodeled source fields.
- Reporting views/materialized views expose current state and expensive
  aggregates.

## Read and write surfaces

- Operations is the destination for operational reporting, administration,
  workflow, and operator decisions.
- New reporting reads generic current evidence, canonical state, findings, and
  compact rollups through tenant-safe Operations read models.

## Deployment boundary

- Repository files required at runtime must be baked into images.
- Secrets and persistent configuration are mounted from outside Git.
- Postgres persistent data uses managed Docker storage. The retired Metabase
  application archive is stored locally outside the live stack.
- A push can cause an automatic production redeploy.

## Module boundary

Detailed Operations architecture lives in
`operations/docs/architecture.md`. Root architecture defines how Operations
fits into the stack and how it interacts with ingest and reporting.
