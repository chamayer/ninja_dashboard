# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [0.5.1] — 2026-06-03

### Fixed
- Patch Coverage by OS card: `ORDER BY (active + stale + no_data)`
  referenced column aliases inside arithmetic — Postgres doesn't
  allow that at the same SELECT level. Switched to `ORDER BY
  COUNT(*) DESC` (same result, valid SQL).

## [0.5.0] — 2026-06-03

### Added — interactive dashboards

Click-behavior wired across charts and tables, enabled by a new
two-pass provisioning model: pass 1 creates cards / dashboards /
layouts, pass 2 applies `click_behavior` (needs dashboard IDs from
pass 1 for cross-dashboard drill-through).

  - **Charts**: click a slice / bar to filter. Pies, severity bars,
    top-N bars all wired. Cross-filter (same dashboard) or drill-link
    (other dashboard) depending on which makes sense.
  - **Table columns**: per-column click behavior in all major tables.
    Click a Device cell → opens Device Drilldown for that device.
    Click an Org / Status / KB / Node Class cell → cross-filters the
    current dashboard.

Specific wires:

  - Overview pie → opens Detail filtered by status
  - Overview compliance bar → opens Detail filtered by org
  - Overview compliance table (org column) → opens Detail by org
  - Overview reboot table (device col) → Drilldown; (org col) → Detail
  - Detail pies/bars → self-filter the Detail dashboard
  - Detail tables (device col) → Drilldown
  - Detail top-devices bar → Drilldown for the clicked device
  - Drilldown patch history (kb col) → Detail filtered by KB
  - Patch Coverage pies/bars → self-filter the Coverage dashboard
  - Patch Coverage device col → Drilldown

### Changed

- Node Class filter defaults to `WINDOWS_WORKSTATION` on Detail and
  Patch Coverage. MSP "workstations first" workflow now is the
  default view; pick `WINDOWS_SERVER` / others from the dropdown.

### Process

- VERSION 0.5.0. Two-pass provisioning is a meaningful architecture
  change to the bootstrap script (worth tracking).

## [0.4.0] — 2026-06-03

### Added
- New SQL view `ninja_core.v_active_devices` defined as: approved
  AND last contact within 30 days. The view exposes the latest
  device_snapshots fields inline (`last_contact`, `last_boot`,
  `needs_reboot`, `maintenance_*`, etc.) so downstream queries
  don't need to re-join the snapshots table.
- Migration `004_active_devices_view.sql` creates the view on next
  container start (run by ingest.migrations).
- Patch Coverage all-devices table gains `last_contact` and
  `days_since_contact` columns. Combined with `patch_status`,
  operators can spot devices that are both stale-patching AND
  hardware-unreachable (decommission candidates) vs stale-patching
  but contactable (agent / config problem).

### Changed (behavioral)
- **Overview and Detail dashboards now filter to "active devices"**
  (the new view's definition). Counts, compliance %, top-N, all-orgs,
  and the patch detail table all narrow to the active fleet.
- Drilldown deliberately stays on raw `ninja_core.devices` so you
  can still investigate inactive / decommissioned devices.
- Patch Coverage deliberately stays on raw devices so it surfaces
  the very devices the active-view excludes.

### Process
- VERSION bumped to 0.4.0 — semantic change to default scope of
  multiple dashboards is a MINOR bump even though backward-
  compatible at the SQL level.

## [0.3.1] — 2026-06-03

### Added
- Overview gains a "Patch Coverage" summary row: Active (last 7d) /
  Stale (>7d) / No Data Ever — three numbers above the existing
  pie/compliance row. Subsequent rows shifted down accordingly.
- Patch Coverage dashboard:
  - **Stale threshold (days)** dashboard parameter — operator picks
    the cutoff at the top, default 7. CTE uses it dynamically.
  - **Node Class pie** — breakdown of devices in the current filter
    set by node_class.
  - **OS stacked bar** (top 20 OSes) — for each OS, active vs stale
    vs no_data counts. Best way to see if a particular Windows /
    Linux / Mac flavor has a coverage problem.
- Detail dashboard: **Timeline window (days)** parameter, default 90.
  Only the install-timeline card maps it; others ignore.
- Drilldown dashboard: **Timeline window (days)** parameter, default
  180. Same pattern.

### Process
- VERSION bumped to 0.3.1 (additive features + UX polish, no breaking
  changes).

## [0.3.0] — 2026-06-03

Dashboards stage. Stack now ships three Metabase dashboards
auto-provisioned on container startup; bootstrap script is
operator-set-and-forget.

### Added
- `ingest/metabase_bootstrap.py` — idempotent CLI + library that
  provisions Metabase collections, cards, dashboards, layouts via
  REST API. Supports template-tag-based dashboard filters with
  dropdown sources populated from live Postgres data.
- Auto-bootstrap on ingest container startup, gated on
  `MB_BOOTSTRAP_USER` / `MB_BOOTSTRAP_PASS` env vars. Waits up to
  5 min for Metabase to come up, checks first-run wizard is
  complete, tolerates all failures (logged, not raised).
- `POST /bootstrap-metabase` HTTP endpoint for manual re-provision
  without container restart.
- Dashboard: **Ninja — Overview** — 9 cards: active devices,
  patches ready / manual+delayed / failed (numbers); patch state
  donut; worst-15 + all-orgs compliance; reboot table; ingest
  health.
- Dashboard: **Ninja — Patch Detail (Filterable)** — 8 cards behind
  6 dashboard filters (Org dropdown, Status, Node Class, Severity,
  OS Name, KB Number). Status donut, severity bar, top-15 + all
  devices, top-20 + all KBs, install timeline, full patch table.
- Dashboard: **Ninja — Device Drilldown** — per-device deep dive
  via free-text name search. Device info, patch state pie, 180-day
  install timeline, full patch history table (every SCD-2 row).
- Dashboard: **Ninja — Patch Coverage** — operational gap analysis.
  Classifies each approved device as active_patching /
  stale_patch_data / no_patch_data based on the most recent
  observation in patch_facts. Filters by Org / Node Class / OS /
  Patch Status. Useful for finding devices the patch agent is no
  longer reaching.
- `ingest/probe.py` + `ingest/probe_fields.py` — diagnostic CLIs
  for walking unknown Ninja endpoints and surveying custom-field
  shape before writing ingest code.

### Fixed
- `paginate_cursor` was infinite-looping on Ninja's `/queries/*`
  endpoints because cursor.name stays constant across pages.
  Termination now driven by `cursor.offset + len(results) >=
  cursor.count`.
- All pie charts show every slice (`pie.slice_threshold: 0`); the
  default 2.5% threshold was hiding small statuses as "Other".
- COUNT columns renamed from `n` to `patches` so tooltips read
  "patches: 47" instead of "n: 47".

### Process
- Going forward, VERSION bumps on each feature/fix commit; tags
  cut at milestones. CHANGELOG.md updated per commit.

## [0.2.0] — 2026-06-03

End-to-end ingest pipeline running against a live Ninja instance.
Stack is deployed on `am-ch-01` via Portainer git auto-update.

### Added
- Full ingest of organizations / locations / policies / devices /
  device_snapshots / custom_field_values / patch_facts / activities
  from `amrose.rmmservice.com`.
- `ingest/runlog.py` — reusable context manager that opens and
  closes a `ninja_core.run_log` row per module.
- `ingest/main.py` — APScheduler + threading HTTP server (`/healthz`,
  `/run`) wired through `_safe()` so a module crash doesn't kill the
  rest of the cycle.
- `ingest/util.py` — `ninja_epoch_to_dt`, `content_hash`.
- `ingest/probe.py` + `ingest/probe_fields.py` — diagnostic CLIs for
  walking endpoints and discovering custom field schemas without
  writing to the DB.
- `ingest/db.insert_ignore` — bulk INSERT ... ON CONFLICT DO NOTHING
  for immutable-event tables (`ninja_activities.activities`).
- `db.upsert(..., update_cols=...)` — column-scoped UPDATE for SCD-2
  tables that must preserve `first_observed_at`.
- Custom fields allowlist + value-size cap
  (`INGEST_CUSTOM_FIELDS_INCLUDE`, `INGEST_CUSTOM_FIELDS_MAX_TEXT`)
  so we don't ingest 20k-char HTML reboot reports into typed cells.
- Patches: batched upserts (5000 rows at a time) for memory bounded
  ingest of 376k+ patch records.

### Fixed
- `migrations.py` was importing `pool` directly from `ingest.db`,
  capturing the pre-init sentinel; switched to module reference.
- `paginate_cursor` was infinite-looping because Ninja keeps the
  cursor name constant across pages on `/queries/*` endpoints.
  Termination is now driven by `cursor.offset + len(results) >=
  cursor.count`, with stalled-offset detection as a guard.
- Postgres healthcheck was generating `FATAL role "root"` spam every
  10s — switched to socket-based `pg_isready -h /var/run/postgresql`
  so it bypasses `pg_hba` host rules.
- Init script renamed from bash to sh — `postgres:16-alpine` doesn't
  ship bash.
- `postgres.Dockerfile` bakes the init script into a custom image
  because Portainer Repository-mode doesn't extract repo files for
  runtime bind-mounts.
- `postgres-data` and `metabase-data` moved from host bind-mounts to
  named docker volumes — eliminates chown/wipe foot-guns.
- Compose env handling settled on bind-mount + entrypoint wrapper
  (`set -a; . /etc/secrets.env; set +a; exec ...`) since neither
  `${VAR}` substitution nor `env_file:` work in Portainer
  Repository-mode.

### Known limitations
- `custom_field_definitions` table is unpopulated; the live API has
  118 defined fields but only the 19 with `apiPermission != NONE`
  return values via `/queries/custom-fields`. Switching to a
  two-endpoint (`/v2/custom-fields` definitions + `/queries/
  scoped-custom-fields-detailed` values) parked for v0.3.
- Activities first run sets the cursor but doesn't backfill — only
  events newer than the cursor flow in. Backfill script is TODO.
- `needs_reboot_reasons` is captured as NULL on `device_snapshots`;
  need to confirm where Ninja exposes Windows reboot reasons.

## [0.1.0] — 2026-06-02

Initial scaffold. No working ingest yet — package layout, Docker
stack definition, database schemas, and supporting docs only.

### Added
- `REQUIREMENTS.md` — full design doc: architecture, decisions, schema,
  scope, expansion path.
- `CONTEXT.md` — project overview for new contributors / future sessions.
- `docker-compose.yml` — three-service stack (postgres, metabase,
  ingest).
- `Dockerfile` — Python 3.12-slim, non-root, healthcheck.
- `requirements.txt` — pinned ingest deps (httpx, psycopg, apscheduler,
  pydantic-settings, python-dotenv).
- `.env.example` — required environment variables.
- `ingest/` Python package skeleton: `config`, `ninja_client`, `db`,
  `migrations`, `main`, `core/`, `patches/`. No logic yet.
- `sql/init/00_create_databases.sh` — creates `ninja` and `metabase`
  databases + the `metabase` app user on first Postgres boot.
- `sql/migrations/001_init_core.sql` — `ninja_core` schema (orgs,
  locations, policies, devices, device_snapshots, custom fields,
  run_log, schema_migrations). SCD-2 baked into custom_field_values.
- `sql/migrations/002_patches.sql` — `ninja_patches.patch_facts`
  with SCD-2 / content-hash dedup.
- `sql/migrations/003_activities.sql` — `ninja_core.ingest_state` +
  `ninja_activities.activities`, filtered to patch lifecycle events
  + SYSTEM_REBOOTED.
- `ingest/activities/` package skeleton.
- `ingest/ninja_client.py` — implemented: OAuth2 client-credentials
  auth with token refresh, retry/backoff on 5xx/429, both pagination
  styles (`paginate_after`, `paginate_cursor`).
- `ingest/db.py` — implemented: psycopg-pool `ConnectionPool`,
  `transaction()` context manager, generic `upsert()` helper.
- `ingest/migrations.py` — implemented: discover `sql/migrations/*.sql`,
  apply pending in transaction-per-file, idempotent bootstrap.
- `ingest/smoke.py` — `python -m ingest.smoke` end-to-end sanity check
  (env → Postgres → migrations → Ninja API).
- `psycopg-pool==3.2.3` added to `requirements.txt`.
- `docker-compose.yml`: every service now uses
  `env_file: /amr-ch-01_data/ninja-dashboard/.env` instead of
  `${VAR}` substitution. Host `.env` is the single source of truth;
  no Portainer-side env panel needed. Pg healthcheck rewritten to
  use `$$VAR` shell-time substitution.
- **Compose env handling rewritten** (the saga's resolution): env
  vars come from the bind-mounted host `.env` read by each container
  at startup. Postgres + Metabase use entrypoint wrappers that source
  `/etc/secrets.env`; ingest uses python-dotenv on `/app/.env`.
  Sidesteps every Portainer-Repository-mode limitation (no
  `${VAR}`, no `env_file:` with abs paths, no repo-relative bind
  mounts at runtime).
- **Postgres init script baked into custom image** via
  `postgres.Dockerfile` instead of bind-mounted from `./sql/init`.
  The bind-mount path was always empty in Portainer Repository mode
  because Portainer doesn't extract repo files to disk for runtime
  use — only for build contexts.
- **Renamed `Dockerfile` → `ingest.Dockerfile`**; postgres now has
  its own `postgres.Dockerfile`. Both built by Portainer on push.
- **Switched `postgres-data` and `metabase-data` to auto-managed
  named volumes** instead of host bind-mounts under
  `/amr-ch-01_data/ninja-dashboard/`. Eliminates the chown/wipe
  foot-guns; `docker volume rm` is the unambiguous reset.
- Postgres healthcheck simplified to bare `pg_isready` (no env
  needed; docker exec doesn't inherit the entrypoint wrapper's env).
- `PORTS.md` — host port map + what this stack publishes
  (3001 Metabase on LAN; 8090 ingest on loopback; Postgres internal).
- `TODO.md`, `SESSIONS.md` per `Development/DEVELOPMENT.md` conventions.
- `.gitignore`, `.dockerignore`.
