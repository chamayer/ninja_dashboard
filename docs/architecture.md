# Ninja Dashboard architecture

## System overview

```text
Ninja and other sources
        │
        ▼
Operations Ingest Engine
        │ raw/source schemas + migrations
        ▼
Postgres
   ├── Metabase dashboards
   └── Operations Django application
            ├── canonical entities
            ├── identity and client resolution
            ├── findings and notification workflows
            └── operator decisions
```

The repository builds custom Postgres, ingest, and Operations images and runs
Metabase as an upstream image.

## Repository layers

| Path | Responsibility |
|---|---|
| `ingest/` | Schedulers, source connectors, migrations, domain processing |
| `sql/init/` | First-boot database initialization |
| `sql/migrations/` | Ingest-managed SQL schema evolution |
| `ingest/metabase_bootstrap.py` and module bootstraps | Dashboard definitions |
| `operations/` | Django/DRF/HTMX operator control plane |
| `docker-compose.yml` and `*.Dockerfile` | Runtime packaging and orchestration |

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

- Metabase is the read/exploration surface for dashboards.
- Operations is the write-side workflow and control-plane surface.
- Metabase should not become the authority for operator decisions.
- Operations should not duplicate raw reporting when a read-only dashboard is
  sufficient.

## Deployment boundary

- Repository files required at runtime must be baked into images.
- Secrets and persistent configuration are mounted from outside Git.
- Postgres and Metabase persistent data use managed Docker storage.
- A push can cause an automatic production redeploy.

## Module boundary

Detailed Operations architecture lives in
`operations/docs/architecture.md`. Root architecture defines how Operations
fits into the stack and how it interacts with ingest and reporting.
