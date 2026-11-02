# Ninja Dashboard

Ninja Dashboard is an internal operations stack that ingests source data into
Postgres and provides reporting, operator workflows, and administration
through the Django Operations application.

## Services

- `postgres` — durable source and Operations data
- `ingest` — scheduled source collection, migrations, derived refresh, and
  manual operator endpoints
- `operations` — tenant-aware findings, decisions, configuration, and workflow
  UI

## Repository layout

```text
ingest/                    Python ingest engine and connectors
sql/                       Postgres initialization and ingest migrations
operations/                Django/DRF/HTMX Operations application
docker/                    Shared infrastructure image definitions
docker-compose.yml         Stack definition
*/Dockerfile               Service image definitions
docs/                      Root requirements, architecture, state, operations
BLUEPRINT.md                Current root or cross-service work
VERSION                    Stack version
CHANGELOG.md               Release-visible history
```

## Development

The full stack is designed to run through Docker Compose. Production services
run on an internal Docker host and can be automatically redeployed after an
approved push.

### Full local development stack

Use `docker-compose.dev.yml` for a separate local Postgres, ingest service,
Jobs worker, and Operations app. It uses the `ninja_dev` database, its own
Docker volume, and loopback-only ports; it does not mount production files or
connect to the production database. Scheduled Jobs are disabled. Notification
settings come from `.env.dev`, so manually triggered Jobs can use live source
and notification integrations if their production credentials are copied.

1. Copy `.env.dev.example` to `.env.dev` and set local database, Django, and
   admin credentials. Keep those local values when importing production
   settings. Never copy production database credentials into `.env.dev`.
2. Start the stack:

   ```powershell
   docker compose -p ninja-dashboard-dev -f docker-compose.dev.yml up --build -d
   ```

   If workstation HTTPS inspection re-signs PyPI traffic, use the local-only
   BuildKit CA secret described above and add
   `-f docker-compose.dev.workstation-ca.yml` to the command. This passes the
   certificate only during dependency installation and keeps TLS verification
   enabled.
3. Open Operations at <http://localhost:3003>. The initial admin password is
   `OPERATIONS_INITIAL_ADMIN_PASSWORD` from `.env.dev`.
4. Configure local source instances and bindings in Django Admin at
   <http://localhost:3003/admin/>. Keep the source and binding enabled, and
   leave its schedule blank for manual-only use. Run its initial collection
   from the Sources page; later refreshes are operator-triggered there too.

To copy production application settings into `.env.dev`, merge non-local
settings by variable name instead of appending duplicate lines. Keep local
database, host, Django secret, and admin-password values. The local Compose
configuration forces `SCHEDULED_JOBS_ENABLED=false`; manual jobs still use
copied credentials. Manual Jobs may read production sources or send messages,
tickets, or webhooks to their configured live destinations.
If a PowerShell merge rewrites `.env.dev`, write it with LF line endings:
Operations' startup reader uses a POSIX shell parser that treats CRLF's `\r`
as part of a value.

```powershell
$envPath = (Resolve-Path -LiteralPath '.env.dev').Path
$envText = [System.IO.File]::ReadAllText($envPath) -replace '\r\n?', "`n"
[System.IO.File]::WriteAllText($envPath, $envText, [System.Text.UTF8Encoding]::new($false))
```

Ingest and Django apply their normal pending migrations to this local database
on startup. Validate changes here before pushing code. The approved `origin`
push still triggers production deployment and applies pending migrations
there; the local database itself is never promoted or copied to production.

To stop the services while preserving local data, run:

```powershell
docker compose -p ninja-dashboard-dev -f docker-compose.dev.yml down
```

To erase the local database and start from scratch, stop the stack and remove
only its named local volume:

```powershell
docker volume rm ninja-dashboard-dev_ninja-dev-postgres-data
```

Review the exact volume name with `docker volume ls` first if the Compose
project name was changed. Source-specific refreshes are triggered from the
Sources page; other scheduled Jobs can be run manually from the Jobs page.

Local Docker Desktop with the WSL 2 backend may be used for disposable Compose
dependencies and PostgreSQL integration tests. Local containers must use
test-created data only and must never be configured to target a deployed
database or service.

If workstation HTTPS inspection re-signs PyPI traffic, export the trusted
inspection root as a PEM certificate outside the repository and start the dev
stack with its optional BuildKit CA secret. TLS verification stays enabled:

```powershell
$env:NINJA_LOCAL_CA_PEM = Get-Content -LiteralPath (Join-Path $env:USERPROFILE '.docker/ninja-dashboard/workstation-ca.crt') -Raw
try {
  docker compose -p ninja-dashboard-dev -f docker-compose.dev.yml -f docker-compose.dev.workstation-ca.yml up --build -d
} finally {
  Remove-Item Env:NINJA_LOCAL_CA_PEM -ErrorAction SilentlyContinue
}
```

The local-only override passes the certificate to dependency-install builds
through a temporary environment secret. It is mounted only during dependency
installation and is neither copied into the final image nor required by normal
or production builds. Never commit the certificate or disable certificate
verification.

Read:

- `AGENTS.md` before changing the repository.
- `docs/architecture.md` for cross-service or storage changes.
- `operations/AGENTS.md` before changing Operations.
- The applicable `BLUEPRINT.md` for active nontrivial work.

## Validation

Validation depends on the changed layer:

- Python syntax/import checks for ingest
- SQL and migration-order review
- Django, Ruff, focused tests, and request/template checks for Operations
- Dockerfile and Compose packaging review

Do not claim production validation from local files alone.
