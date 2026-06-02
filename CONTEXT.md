# Context — ninja-dashboard

> Read this before making changes. For requirements / decisions, see
> `REQUIREMENTS.md`. For the cross-project standards this project
> follows, see `Development/DEVELOPMENT.md`.

## What it does

Pulls data from the NinjaOne RMM v2 API on a schedule, lands it in
Postgres, and exposes filterable dashboards via Metabase. Runs
unattended on the internal Docker host (`am-ch-01`, `10.61.50.28`),
deployed by Portainer from this git repo.

**v1 scope:** two domains.

- **patches** — primary. Compliance %, pending/failed/installed,
  state-transition history, trends.
- **activities** — enrichment. Filtered slice of Ninja's built-in
  event log; patch application + lifecycle events only. Joined to
  patches for the "what happened around this install?" context.

The architecture supports additional Ninja domains (tickets, alerts,
jobs, AV, etc.) as drop-in modules — see `REQUIREMENTS.md` §9.

## Architecture at a glance

```
Ninja API ──► ingest (Python) ──► Postgres ◄── Metabase ──► browser
                  │
                  └──► writes run_log row each run
```

Three containers, one Compose file. `ingest` is built from this repo;
`postgres` and `metabase` are upstream images.

## Repo layout

```
├── docker-compose.yml          # 3-service stack
├── ingest.Dockerfile           # ingest container (Python)
├── postgres.Dockerfile         # postgres:16-alpine + baked init script
├── requirements.txt            # pinned Python deps
├── .env.example                # template (real .env lives on host)
├── ingest/                     # Python package
│   ├── config.py               # env-based config
│   ├── ninja_client.py         # Ninja API client (auth + pagination)
│   ├── db.py                   # Postgres connection helpers
│   ├── migrations.py           # applies sql/migrations/*.sql on startup
│   ├── main.py                 # scheduler entry point
│   ├── core/                   # shared-data ingest modules
│   │   ├── organizations.py
│   │   ├── locations.py
│   │   ├── policies.py
│   │   ├── devices.py
│   │   └── custom_fields.py
│   ├── patches/                # primary domain
│   │   └── ingest.py
│   └── activities/             # enrichment domain (filtered event log)
│       └── ingest.py
├── sql/
│   ├── init/                   # runs once on first Postgres boot
│   │   └── 00_create_databases.sh
│   └── migrations/             # applied by ingest on startup
│       ├── 001_init_core.sql
│       ├── 002_patches.sql
│       └── 003_activities.sql
├── REQUIREMENTS.md             # decisions, schema, scope
├── CONTEXT.md                  # this file
├── PORTS.md                    # host port map + what this stack publishes
├── CHANGELOG.md
├── VERSION
├── SESSIONS.md
└── TODO.md
```

## Data flow

1. **Scheduler** in `ingest/main.py` triggers a run every
   `INGEST_SCHEDULE_HOURS` (default 1h).
2. Each run executes the ingest modules in order:
   - `core/` modules first (orgs, locations, policies, devices, custom
     fields) — populate `ninja_core` schema (shared lookups).
   - Domain modules next (`patches/` for v1) — populate their own
     schema.
3. Every module writes a `ninja_core.run_log` row tagged with `domain`,
   timings, row counts, and error text if it failed.
4. Metabase queries Postgres on each dashboard load (with caching).

## Schema namespacing

- `ninja_core` — always present. Lookups (`organizations`, `locations`,
  `policies`, `devices`), `device_snapshots`, custom fields, `run_log`,
  `ingest_state`, `schema_migrations`.
- `ninja_patches` — primary domain. `patch_facts`.
- `ninja_activities` — enrichment domain. `activities` (filtered to
  patch-management events in v1; sources extensible via
  `INGEST_ACTIVITY_SOURCES`).
- Future domains get their own schema (`ninja_tickets`, etc.); they
  reference `ninja_core` lookups but never alter shared tables.

See `REQUIREMENTS.md` §4 for the full schema.

## Key design choices

- **Ingest, don't query live.** Time-series and offline-resilience
  require local storage. See `REQUIREMENTS.md` §3.1.
- **`data jsonb` column on every table.** Raw API payload kept
  alongside parsed columns. New fields surface without migrations.
- **Custom fields as EAV + auto-pivoted views.** Definitions and
  values in EAV tables; ingest regenerates pivoted views so each
  custom field appears as a real column in Metabase.
- **SCD-2 with content hash** for `patch_facts` and
  `custom_field_values`. New row only when content changes; otherwise
  `last_observed_at` advances on the existing row. Gives full
  state-transition history (PENDING → APPROVED → INSTALLED) per
  natural key without snapshot bloat. Current value reads use
  `DISTINCT ON (...) ORDER BY last_observed_at DESC`.
- **Plain append snapshots** for `device_snapshots` only — its
  volatile fields (`last_contact`) change every minute, so hash-dedup
  would never match. History pruned by a retention job.
- **One ingest credential.** Single Ninja OAuth client; modules share
  the HTTP client and token.

## Ports

See `PORTS.md` for the full host map. This stack publishes:

- **3001** (Metabase) — LAN.
- **8090** (ingest `/healthz`, `/run`) — loopback only.
- Postgres is **not** published — use `docker exec` for ad-hoc shells.

## Local dev

WSL2 + Docker. Bring up the stack with:

```bash
docker compose up --build
```

Metabase at `http://localhost:3001`. Postgres reachable via
`docker exec -it ninja-postgres psql -U ninja -d ninja`.
First boot of Postgres applies `sql/init/*` (creates databases). First
boot of `ingest` applies pending `sql/migrations/*.sql`.

Real-data testing pulls a Postgres backup from the host:

```bash
scp am-ch-01:/amr-ch-01_data/ninja-dashboard/backups/ninja-*.sql ./test-data/
```

## Deploy

Push to GitHub. Portainer's stack for this repo rebuilds and
redeploys on push. Host data and secrets live at
`/amr-ch-01_data/ninja-dashboard/` — at minimum:
- `.env` (chmod 644, owned by root)
- `backups/` (`pg_dump` target)

Postgres + Metabase data live in **named docker volumes**
(`postgres-data`, `metabase-data`) — not host bind-mounts.

### Portainer Repository-mode constraints (read this once)

The constraints below are non-obvious and keep biting people:

- **Repo files exist on disk only during `docker build`**, not at
  runtime. So `volumes: - ./foo:/bar` (repo-relative bind-mount) does
  NOT work — the source dir is empty. Anything needed at runtime must
  either be **baked into the image** (Dockerfile `COPY`) or live under
  `/amr-ch-01_data/<stack>/` as a host file and be bind-mounted by
  absolute path.
- **No `${VAR}` substitution** — Portainer's env-variable panel is
  not honored in repo mode.
- **No `env_file:` with absolute host paths** — Portainer's compose
  process can't see `/amr-ch-01_data/` on its own filesystem.
- **What works:** absolute-path bind-mounts (daemon resolves them
  server-side) and `build:` directives (daemon receives a tar of the
  context).

That's why our compose ships secrets as a bind-mounted `.env` that
each container reads at startup, and ships the postgres init script
via a custom Dockerfile.
