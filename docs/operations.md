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
push target rather than assuming one remote is sufficient. One explicit push
approval may cover both targets as a combined operation; in that case push
`origin` first and the mirror immediately afterward, without inserting a
validation gate between them. Perform post-deployment validation after both
pushes. Read-only external post-deployment validation also requires
authorization under the task's stated external-validation boundary.

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

## Ninja daily-presence backfill

The Ninja daily-presence rollup is backfilled only after its additive schema is
deployed and a successful current Ninja device collection has populated stable
source records. Historical-only devices that disappeared before generic
population must first receive stable withdrawn source evidence through the
separate restoration tool below. Neither tool is a startup migration, and
neither deletes or alters legacy snapshots.

Measure historical-only source evidence for the exact completed UTC-day range
needed by the rollup. Omitting `--apply` is the read-only default and emits only
aggregate counts:

```sh
docker exec operations-ingest \
  python -m ingest.restore_ninja_historical_evidence \
  --start-day YYYY-MM-DD --end-day YYYY-MM-DD
```

Review and separately approve the restoration write before adding `--apply`.
Apply mode fails closed unless every missing identity is a withdrawn legacy
Ninja device with retained raw evidence, a valid observed interval, no generic
current/history evidence, and no canonical Ninja device link. It creates one
inactive generic current record and one closed history interval per identity.
It does not create or link canonical devices, fabricate snapshot runs, alter
legacy rows, or write daily rollups. The operation is atomic and idempotent.

After restoration, rerun the read-only daily-presence measurement over the
complete range and require zero unmatched and zero ambiguous mappings before
approving the rollup write.

Measure an explicit range of completed UTC days first. Omitting `--apply` is
the safe, read-only default and emits aggregate counts only:

```sh
docker exec operations-ingest python -m ingest.backfill_ninja_daily_rollup \
  --start-day YYYY-MM-DD --end-day YYYY-MM-DD
```

Review and separately approve the resulting data write before adding
`--apply`. The tool commits one day at a time, marks legacy-derived provenance
without inventing a snapshot run, aborts on missing or ambiguous source-record
mappings, and is idempotent when a completed range is rerun. The end day must
be earlier than the current UTC day. Historical snapshot archival, deletion,
and disk reclamation remain a separate post-cutover approval.

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
