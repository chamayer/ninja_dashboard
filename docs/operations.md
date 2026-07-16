# Ninja Dashboard operations

This document records environment-independent operational procedures. Private
host values, credentials, tokens, and customer data remain outside Git.

## Deployment model

- Portainer follows the repository and rebuilds the stack after approved
  pushes.
- Postgres, ingest, and Operations use repository-built images.
- Metabase uses its upstream image.
- Runtime configuration and secrets are mounted from external files.
- Repository-relative runtime bind mounts are not reliable in repository-mode
  deployment; runtime files must be baked into images or mounted from approved
  external paths.

## Deployment approval boundary

Commit, push, redeploy, schema migration, data rebuild, destructive cleanup,
restore, and rollback require explicit approval. Commit and push approvals are
separate.
If branches or release tags must be sent to multiple remotes, confirm and
approve each push target rather than assuming one remote is sufficient.

## Pre-deployment checks

- Confirm Dockerfiles copy all new runtime files.
- Confirm entrypoints use the correct shell, role, and environment.
- Confirm Compose dependencies, mounts, health checks, and ports.
- Review ingest SQL and Django migration order.
- Audit consumers before renaming schemas, tables, views, fields, template
  identifiers, or dashboard objects.
- Run the relevant validation documented by root and Operations AGENTS files.

## Migration systems

- `sql/migrations/` is applied by the ingest migration runner.
- `operations/apps/*/migrations/` is applied through Django.
- A change spanning both systems must define dependency and deployment order.
- PostgreSQL variable substitution inside procedural `DO` blocks requires a
  supported mechanism; do not assume ordinary `psql -v` interpolation works.

## Validation after deployment

- Confirm the intended commit is deployed.
- Confirm all containers are healthy.
- Confirm ingest and Operations health endpoints.
- Confirm migration status and inspect startup logs.
- Validate changed data using tenant-aware or database-side queries.
- Exercise the changed dashboard or Operations workflow.
- Report the pushed short hash, deployment result, and functional-validation
  result separately.

## Data and recovery

- Back up Postgres before destructive migrations or rebuilds.
- Preserve operator-authored configuration and decisions during derived-data
  rebuilds.
- Document which tables are canonical, derived, or safe to regenerate.
- Do not restore a database without confirming application/schema
  compatibility.
- Never copy production dumps into Git or documentation staging.

## Shared validation helper

Use the approved shared helper for repeatable external checks so credentials
remain in private profiles. Documentation should show safe command shapes, not
secret values.
