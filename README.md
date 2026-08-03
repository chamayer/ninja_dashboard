# Ninja Dashboard

Ninja Dashboard is an internal operations stack that ingests source data into
Postgres, serves reporting through Metabase, and provides write-side operator
workflows through the Django Operations application.

## Services

- `postgres` — durable source, reporting, and Operations data
- `ingest` — scheduled source collection, migrations, derived refresh, and
  manual operator endpoints
- `metabase` — read-oriented dashboards and exploration
- `operations` — tenant-aware findings, decisions, configuration, and workflow
  UI

## Repository layout

```text
ingest/                    Python ingest engine and connectors
sql/                       Postgres initialization and ingest migrations
operations/                Django/DRF/HTMX Operations application
docker-compose.yml         Stack definition
*.Dockerfile               Custom service images
docs/                      Root requirements, architecture, state, operations
.work/plan.md              Current root or cross-service work
VERSION                    Stack version
CHANGELOG.md               Release-visible history
```

## Development

The full stack is designed to run through Docker Compose. Production services
run on an internal Docker host and can be automatically redeployed after an
approved push.

Local Docker Desktop with the WSL 2 backend may be used for disposable Compose
dependencies and PostgreSQL integration tests. Local containers must use
test-created data only and must never be configured to target a deployed
database or service.

If workstation HTTPS inspection re-signs PyPI traffic, the application
Dockerfiles accept an optional BuildKit secret named `workstation_ca`. Export
the trusted inspection root as a PEM certificate outside the repository, then
build with TLS verification still enabled:

```powershell
$env:NINJA_LOCAL_CA_PEM = Get-Content "$env:USERPROFILE\.docker\ninja-dashboard\workstation-ca.crt" -Raw
docker compose -f docker-compose.yml -f docker-compose.workstation-ca.yml build ingest operations
Remove-Item Env:NINJA_LOCAL_CA_PEM
```

The explicitly selected override passes the certificate only to those two
builds through that temporary environment secret; Portainer and ordinary
Compose use only `docker-compose.yml`. The certificate is mounted only during
dependency installation, removed in the same image layer, and is neither
copied into the final image nor required by normal or production builds. Never
commit the certificate or replace this with disabled certificate verification
or trusted-host exceptions.

Read:

- `AGENTS.md` before changing the repository.
- `docs/architecture.md` for cross-service or storage changes.
- `operations/AGENTS.md` before changing Operations.
- The applicable `.work/plan.md` for active nontrivial work.

## Validation

Validation depends on the changed layer:

- Python syntax/import checks for ingest
- SQL and migration-order review
- Generated dashboard inspection for Metabase changes
- Django, Ruff, focused tests, and request/template checks for Operations
- Dockerfile and Compose packaging review

Do not claim production validation from local files alone.
