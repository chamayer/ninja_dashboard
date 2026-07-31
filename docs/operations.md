# Ninja Dashboard operations

This document records environment-independent operational procedures. Private
host values, credentials, tokens, and customer data remain outside Git.

## Deployment model

- Portainer follows `origin` (`chamayer/ninja_dashboard`, `master`) and
  rebuilds the stack after approved pushes. This is the deployment authority.
- `a-m-rose/ninja_dashboard` is the required secondary mirror. Push the same
  approved commit there after `origin`; it is not the repository Portainer
  watches.
- Postgres, ingest, and Operations use repository-built images.
- Metabase uses its upstream image.
- Runtime configuration and secrets are mounted from external files.
- Repository-relative runtime bind mounts are not reliable in repository-mode
  deployment; runtime files must be baked into images or mounted from approved
  external paths.

## Deployment approval boundary

Commit, push, redeploy, schema migration, data rebuild, destructive cleanup,
restore, and rollback require explicit approval. Commit approval is separate
from production push approval.

The current GitOps path has one coupled production boundary:

1. Pushing `origin` causes Portainer to rebuild/recreate the stack.
2. Ingest startup applies pending `sql/migrations/` entries.
3. Operations startup runs `python manage.py migrate --noinput` with the
   migration role before switching to the runtime role.

Pending migrations must therefore be reviewed, backed up as required, and
explicitly included in the `origin` push approval. Do not approve or describe
an `origin` push while deferring its automatic deployment or startup migrations
to a later gate. A manual redeploy, manual migration rerun, data operation,
rollback, or restore remains a separate approval boundary.

Deployment commits must be pushed to both remotes: first `origin`
(`chamayer/ninja_dashboard`) under the coupled approval above, then
`a-m-rose/ninja_dashboard` as the secondary mirror. Confirm and approve each
push target rather than assuming one remote is sufficient. Read-only external
post-deployment validation also requires authorization under the task's stated
external-validation boundary.

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
- Both runners execute automatically during service startup after the GitOps
  deployment; their pending migration sets are part of pre-push review.
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

From the repository root, invoke it through Windows PowerShell 5.1:

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File ..\Scripts\Invoke-DevTool.ps1 <profile> <GET|POST|PUT|DELETE|ssh> <target>
```

Profiles are machine-local in `%USERPROFILE%\.config\amrose-dev\tools.json`;
secret values remain in its referenced untracked environment files. Never
print or copy those values. Helper availability is not authorization: use
read-only checks only when relevant to the task, and obtain explicit approval
for POST, PUT, DELETE, redeploy, migration, or any other state-changing action.
