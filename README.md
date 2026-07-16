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
