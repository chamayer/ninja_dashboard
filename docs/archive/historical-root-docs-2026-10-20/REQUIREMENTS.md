# Ninja Dashboard — Requirements

## 1. Goal

A self-hosted, always-on dashboard that visualizes data pulled from the
NinjaOne RMM API. Filterable by organization, device type, status,
custom fields, and date; high-level status rollups and time-series
trends. No dependency on an admin workstation or human-triggered runs.

**Scope framing:** the project is a general-purpose Ninja dashboard
platform. **v1 ships two domains:**

- **`patches`** — primary. Patch state, compliance, install/failure
  history.
- **`activities`** — enrichment. Filtered subset of Ninja's built-in
  event log (`/v2/activities`), scoped to:
    - `PATCH_MANAGEMENT_APPLY_PATCH_*` / `_PATCH_APPROVED` / `_PATCH_REJECTED` / `_ROLLBACK_PATCH_*` / `_MESSAGE` / `_FAILURE` — patch lifecycle.
    - `SYSTEM_REBOOTED` — closes the loop on post-patch reboots.

  Used to answer "what actually happened around this patch?" and "did
  the reboot we needed actually happen?". Scan events and patch-agent
  install events are excluded as noise.

Tickets, alerts, jobs, antivirus, software inventory, backups, etc. are
deliberately on the expansion path (see §9). The architecture, naming,
and database schema are designed so adding a new domain = a new ingest
module + a new database schema, with zero touch to existing tables.

Replaces the current workflow of running `Ninja-Patching-report.ps1`
manually on a laptop and exporting CSVs.

---

## 2. Architecture

Single-host Docker Compose stack on the internal Docker host
(`am-ch-01`, `10.61.50.28`), auto-deployed by Portainer from this git
repo — same pattern as the `dmarc` stack.

| Container  | Role                                                  |
| ---------- | ----------------------------------------------------- |
| `ingest`   | Python service. Pulls Ninja API, writes Postgres.     |
| `postgres` | Stores current state + historical snapshots.          |
| `metabase` | Dashboard UI (read-only Postgres user).               |

```
            ┌──────────┐ scheduled  ┌────────────┐
NinjaOne ──►│  ingest  │──────────► │  postgres  │◄──── metabase ──► users
   API      └──────────┘  upsert    └────────────┘       (browser)
```

### Deployment pattern (mirrors `dmarc`)

- `docker-compose.yml` at repo root; Portainer rebuilds/redeploys on git push.
- Host-side persistent dir: `/amr-ch-01_data/ninja-dashboard/`
  - `.env` — secrets, gitignored, `chmod 600`, provisioned on host once.
  - `postgres-data/` — bind-mount (see §9 decision).
  - `metabase-data/` — bind-mount.
  - `backups/` — `pg_dump` target.
- `.env.example` committed; real `.env` lives on host and is bind-mounted into the `ingest` container at `/app/.env` (Daemon-side bind-mount works even when Portainer's compose CLI can't see the host path — same trick as dmarc).
- `ingest` built from this repo's `Dockerfile`; `postgres` and `metabase` pulled from upstream images.
- LAN-only by default. No reverse proxy currently on `am-ch-01` — services expose raw ports.

### Repository

- Private GitHub repo.
- Dual remotes per project convention:
  - `origin` → `github.com/chamayer/ninja-dashboard`
  - `a-m-rose` → `github.com/a-m-rose/ninja-dashboard`

---

## 3. Key Decisions

### 3.1 SQL store (rejected: live API queries)

**Decision:** ingest the Ninja API into Postgres on a schedule; Metabase reads Postgres. No live API queries from dashboards.

Re-evaluated against the "Grafana + Infinity hits the Ninja API live" approach from the reference PDF and rejected because:

- **No history = no time-series.** "Pending patches over time", "compliance % trend per org", "offline devices over time" require snapshots that only exist if we store them. This requirement alone settles it.
- Every dashboard load would hit the Ninja API: rate limits, latency, blank dashboards when Ninja has an outage.
- Cross-domain joins (patches × device metadata × org) would have to happen client-side per panel.
- Can't index, aggregate, denormalize, or annotate what we don't store.

One thing kept from the API-direct philosophy: **store the raw API response alongside parsed columns** (jsonb), so when Ninja adds a field we don't need a migration to surface it.

### 3.2 Dashboard: Metabase

**Decision:** Metabase (open-source edition).

Chosen over Grafana and over a custom Flask app:

- Primary use is **relational slicing** (org / type / status / custom field / date), where Metabase's filter UX, drilldowns, and click-to-sort are native — building this in Flask is multiple weeks of UI work, Grafana variables are clunkier.
- Free CSV/Excel export, user management, dashboard permissions.
- New chart = click + SQL, no code deploy.
- Easier to hand read-only dashboards to clients later (per the PDF's stated goal).

Tradeoffs accepted:
- Less branded/custom than a Flask app. **Mitigation:** if/when a polished branded view is needed (monthly per-client export, interactive workflows), build a small Flask app that queries the *same* Postgres — best of both. Going Metabase → custom later is much easier than custom → Metabase.
- Grafana has stronger alerting. **Mitigation:** Grafana can be added alongside Metabase and point at the same Postgres if alerting becomes a real need.

### 3.3 Ingest: Python (port from PowerShell)

**Decision:** Python 3.12.

Chosen over containerizing the existing PowerShell script because:
- Native Postgres support (`psycopg`), proper testing tools, ubiquitous in Linux/Docker.
- Easier handover and long-term maintenance.
- Current script is mostly REST + pagination — port is bounded work.

`Ninja-Patching-report.ps1` stays where it is as a working reference and manual fallback until the Python ingest is proven in production.

### 3.4 Storage: Postgres (rejected: SQLite)

**Decision:** Postgres 16.

SQLite would technically handle current volume, but Postgres wins for:
- First-class Metabase driver, jsonb support, GIN indexes, concurrent writes.
- Schema namespacing (one logical DB, many schemas per domain — see §4).
- No real cost vs SQLite at this stack size (a few hundred MB RAM).

### 3.5 Repo visibility: private

Private GitHub repo. Justified because even with secrets in `.env`, the repo references the internal Ninja instance URL, host IPs, and Ninja client-ID format — better to keep all of it off public GitHub.

---

## 4. Data Model

### 4.1 Structural conventions

- **Schemas per domain.** `ninja_core` (lookups + shared infra) is always present; each ingest domain owns its own schema (`ninja_patches`, future: `ninja_tickets`, `ninja_alerts`, etc.). New domains never touch existing schemas.
- **Every fact/lookup table has a `data jsonb` column** holding the raw API payload. Fields we filter/index/join on are promoted to real columns; everything else stays in `data` and is queryable in Metabase via `data->>'fieldName'`. Adding a panel never requires a migration.
- **Naming by data shape:**
  - `*` (no suffix) = slowly-changing dimension, upserted (orgs, devices)
  - `*_snapshots` = observed state at a point in time, append-only — used only when fields tick constantly and dedup would never apply (e.g. `device_snapshots.last_contact`)
  - `*_facts` = SCD-2 / hash-dedup state-or-event history (`patch_facts`)
  - `*_definitions` = metadata describing user-defined fields
  - `*_values` = EAV-style values keyed by definition, SCD-2 / hash-dedup (`custom_field_values`)
- **SCD-2 / hash-dedup pattern** — applied to `patch_facts` and `custom_field_values`. A new row is inserted only when the content hash changes; otherwise the existing row's `last_observed_at` advances. Gives full state-transition history per natural key without snapshot bloat. Standard write:

  ```sql
  INSERT INTO <table> (..., content_hash, first_observed_at, last_observed_at, ...)
  VALUES (..., :hash, :now, :now, ...)
  ON CONFLICT (<natural_key>, content_hash) DO UPDATE
  SET last_observed_at = EXCLUDED.last_observed_at;
  ```

  Standard "current value" read uses `DISTINCT ON (<natural_key>) ... ORDER BY last_observed_at DESC`.
- **Migrations:** numbered SQL files in `sql/migrations/` (`001_init.sql`, `002_*.sql`...) tracked in `ninja_core.schema_migrations`. The `ingest` container applies pending migrations on startup. No Alembic — overkill at this scale, plain SQL fits the dmarc precedent.

### 4.2 `ninja_core` schema

Shared lookups, device metadata, custom fields, and ingest bookkeeping.

```sql
CREATE SCHEMA ninja_core;

CREATE TABLE ninja_core.organizations (
    id                  integer PRIMARY KEY,
    name                text NOT NULL,
    description         text,
    node_approval_mode  text,                   -- AUTOMATIC | MANUAL | REJECT
    data                jsonb NOT NULL,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ninja_core.locations (
    id              integer PRIMARY KEY,
    organization_id integer NOT NULL REFERENCES ninja_core.organizations(id),
    name            text NOT NULL,
    address         text,
    data            jsonb NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ninja_core.policies (
    id                      integer PRIMARY KEY,
    parent_policy_id        integer,
    name                    text NOT NULL,
    node_class              text,
    is_node_class_default   boolean,
    data                    jsonb NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- Slowly-changing dimension. Upserted on every run.
CREATE TABLE ninja_core.devices (
    id                  integer PRIMARY KEY,
    uid                 uuid UNIQUE NOT NULL,
    organization_id     integer NOT NULL REFERENCES ninja_core.organizations(id),
    location_id         integer REFERENCES ninja_core.locations(id),
    policy_id           integer REFERENCES ninja_core.policies(id),
    role_policy_id      integer REFERENCES ninja_core.policies(id),
    node_class          text NOT NULL,
    approval_status     text NOT NULL,          -- PENDING | STAGED | APPROVED | DECOMMISSIONED
    -- Names (Ninja exposes 4 — store all, compute display in views)
    display_name        text,
    system_name         text,
    dns_name            text,
    netbios_name        text,
    -- OS (promoted from os{})
    os_name             text,
    os_architecture     text,
    os_build_number     text,
    os_release_id       text,
    -- Asset (promoted from system{})
    serial_number       text,
    manufacturer        text,
    model               text,
    chassis_type        text,
    is_virtual_machine  boolean,
    total_memory_bytes  bigint,
    -- Network
    public_ip           inet,
    ip_addresses        text[],
    mac_addresses       text[],
    -- Misc
    tags                text[],
    created_at_ninja    timestamptz,
    -- Raw payload — everything not promoted lives here
    data                jsonb NOT NULL,
    -- Bookkeeping
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON ninja_core.devices (organization_id);
CREATE INDEX ON ninja_core.devices (node_class);
CREATE INDEX ON ninja_core.devices (approval_status);
CREATE INDEX ON ninja_core.devices USING GIN (tags);
CREATE INDEX ON ninja_core.devices USING GIN (data jsonb_path_ops);

-- Append-only state observations. Volatile fields live here, not on `devices`.
CREATE TABLE ninja_core.device_snapshots (
    snapshot_at             timestamptz NOT NULL,
    device_id               integer NOT NULL REFERENCES ninja_core.devices(id),
    offline                 boolean,
    last_contact            timestamptz,
    last_boot               timestamptz,
    needs_reboot            boolean,
    needs_reboot_reasons    text[],               -- e.g. WINDOWS_UPDATE, COMPONENT_BASED_SERVICING, PENDING_FILE_RENAME
    last_user               text,
    maintenance_status      text,                 -- PENDING | IN_MAINTENANCE | FAILED | NULL
    maintenance_start       timestamptz,
    maintenance_end         timestamptz,
    data                    jsonb NOT NULL,
    PRIMARY KEY (snapshot_at, device_id)
);

CREATE INDEX ON ninja_core.device_snapshots (device_id, snapshot_at DESC);
CREATE INDEX ON ninja_core.device_snapshots (needs_reboot) WHERE needs_reboot;
CREATE INDEX ON ninja_core.device_snapshots USING GIN (needs_reboot_reasons);

-- ── Custom fields ─────────────────────────────────────────────────────
-- Definitions (what fields exist) and values (per-entity data). Pivoted
-- per-entity views are auto-regenerated by the ingest job so each known
-- custom field appears as a real column in Metabase.

CREATE TABLE ninja_core.custom_field_definitions (
    id          integer PRIMARY KEY,
    name        text NOT NULL,                  -- programmatic (e.g. "warrantyExpiration")
    label       text,                           -- display label
    scope       text NOT NULL,                  -- DEVICE | ORGANIZATION | LOCATION | NODE_ROLE
    field_type  text NOT NULL,                  -- TEXT | NUMERIC | DATE | DROPDOWN | CHECKBOX | ...
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ON ninja_core.custom_field_definitions (scope, name);

-- SCD-2: insert on hash change, update last_observed_at otherwise.
-- Typed value columns let Metabase do real range/date filters without casting.
CREATE TABLE ninja_core.custom_field_values (
    id                  bigserial PRIMARY KEY,
    entity_type         text NOT NULL,          -- DEVICE | ORGANIZATION | LOCATION
    entity_id           integer NOT NULL,
    field_name          text NOT NULL,
    value_text          text,
    value_number        numeric,
    value_date          timestamptz,
    value_bool          boolean,
    raw_value           jsonb,                  -- original (DROPDOWN options, etc.)
    content_hash        text NOT NULL,
    first_observed_at   timestamptz NOT NULL,
    last_observed_at    timestamptz NOT NULL,
    UNIQUE (entity_type, entity_id, field_name, content_hash)
);

CREATE INDEX ON ninja_core.custom_field_values (entity_type, entity_id);
CREATE INDEX ON ninja_core.custom_field_values (field_name);
CREATE INDEX ON ninja_core.custom_field_values (entity_type, entity_id, field_name, last_observed_at DESC);

-- Auto-regenerated by ingest after each custom_field_definitions refresh.
-- Materializes known fields as real columns for Metabase. Example shape:
--   CREATE OR REPLACE VIEW ninja_core.v_device_custom_fields AS
--   SELECT entity_id AS device_id, snapshot_at,
--          MAX(value_date) FILTER (WHERE field_name = 'warrantyExpiration') AS warranty_expiration,
--          MAX(value_text) FILTER (WHERE field_name = 'department')         AS department,
--          ...
--   FROM ninja_core.custom_field_values WHERE entity_type = 'DEVICE'
--   GROUP BY entity_id, snapshot_at;

-- ── Ingest bookkeeping ────────────────────────────────────────────────

CREATE TABLE ninja_core.run_log (
    run_id          bigserial PRIMARY KEY,
    domain          text NOT NULL,              -- core | patches | tickets | ...
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    status          text NOT NULL,              -- running | ok | failed | partial
    rows_upserted   integer,
    rows_inserted   integer,
    error_text      text,
    duration_ms     integer
);

CREATE INDEX ON ninja_core.run_log (domain, started_at DESC);

CREATE TABLE ninja_core.schema_migrations (
    version     text PRIMARY KEY,               -- "001_init", "002_add_serial", ...
    applied_at  timestamptz NOT NULL DEFAULT now()
);
```

### 4.3 `ninja_patches` schema

First domain. Both Ninja patch endpoints (installed/failed and pending/approved/rejected) land in one fact table, distinguished by `status`.

```sql
CREATE SCHEMA ninja_patches;

-- SCD-2: a (device, patch) row's state changes over time
-- (PENDING → APPROVED → INSTALLED, or REJECTED ↔ PENDING). New row only
-- on hash change; otherwise last_observed_at advances on the existing row.
CREATE TABLE ninja_patches.patch_facts (
    id                  bigserial PRIMARY KEY,
    device_id           integer NOT NULL REFERENCES ninja_core.devices(id),
    patch_uid           uuid NOT NULL,          -- from `id` on Ninja patch
    kb_number           text,
    name                text,
    status              text NOT NULL,          -- INSTALLED | FAILED | PENDING | APPROVED | REJECTED
    severity            text,
    type                text,
    installed_at        timestamptz,            -- nullable for non-INSTALLED
    ninja_observed_at   timestamptz,            -- from Ninja `timestamp` field
    content_hash        text NOT NULL,
    first_observed_at   timestamptz NOT NULL,
    last_observed_at    timestamptz NOT NULL,
    data                jsonb NOT NULL,
    UNIQUE (device_id, patch_uid, content_hash)
);

CREATE INDEX ON ninja_patches.patch_facts (device_id);
CREATE INDEX ON ninja_patches.patch_facts (status);
CREATE INDEX ON ninja_patches.patch_facts (first_observed_at);
CREATE INDEX ON ninja_patches.patch_facts (last_observed_at);
CREATE INDEX ON ninja_patches.patch_facts (installed_at) WHERE installed_at IS NOT NULL;
CREATE INDEX ON ninja_patches.patch_facts (device_id, patch_uid, last_observed_at DESC);
```

### 4.4 Snapshot strategy

- **Cadence:** hourly (default; see §9 open question).
- **`device_snapshots`** (volatile state — `last_contact` ticks constantly): append every run. Retention: keep full for 90 days, then downsample to daily indefinitely (TBD, §9).
- **`custom_field_values` and `patch_facts`** (SCD-2 with content hash): no time-based pruning needed — a new row only exists when something actually changed. The whole transition history is the point.
- **Decommissioned devices:** retained in the DB forever (history is the point) but every dashboard query excludes `approval_status = 'DECOMMISSIONED'` by default.

---

## 5. Dashboards (initial scope)

### Overview (high-level)

- Total active devices, total pending patches, total failed, % compliant.
- Status breakdown (donut): Installed / Pending / Failed / Rejected.
- Compliance % by Org (bar, sortable).
- Compliance % by OS (Windows 10 / 11 / Server 2019 / Server 2022 / Mac / Linux).
- Devices offline > 7 days (count + table).
- Devices needing reboot (count + table) — from latest
  `device_snapshots.needs_reboot`.
- **Patches installed awaiting reboot** — recent `INSTALLED` rows in
  `patch_facts` where the corresponding device's latest
  `device_snapshots.needs_reboot = true` AND no `SYSTEM_REBOOTED`
  activity has happened since the install. Compliance gap that's easy
  to miss.
- Devices with agents not contacted in 30 days (likely dead / decommission candidates).

### Filterable Detail

Global filters: Organization (multi), Node Class, Status, Date range, Severity, OS, **selected custom fields** (Department, Site, Warranty, etc. — auto-populated from `v_device_custom_fields`).

- Patch table: device, KB, name, status, severity, installed_at, days since install. Drilldown to per-device patch history.
- Per-org breakdown: device count by status.
- Per-device drilldown: full patch history + last contact / boot / online trend.

### Trends (time-series)

Available immediately:
- Installs per week (from `installed_at`, single run gives data).

Builds up over snapshots:
- Pending patch count over time (overall + per-org overlay).
- Failed patches over time.
- Offline device count over time.
- Compliance % over time per org.
- Devices added / decommissioned per month.

---

## 6. Non-Functional Requirements

- **Schedule:** ingest runs hourly via APScheduler inside the container. Manual trigger endpoint for ad-hoc runs.
- **Resilience:** per-endpoint retries with exponential backoff; partial-run failures don't corrupt the last good snapshot (each domain's ingest is atomic).
- **Observability:** every run writes a `ninja_core.run_log` row with domain, timings, row counts, and error text.
- **Secrets:** Ninja `ClientId` / `ClientSecret` from environment only. `.env` gitignored, lives on host at `/amr-ch-01_data/ninja-dashboard/.env`. Existing hardcoded credentials in `Ninja-Patching-report.ps1` should be rotated after the Python ingest is live.
- **Backups:** nightly `pg_dump` to `/amr-ch-01_data/ninja-dashboard/backups/`, retention 14 days. Pulled to dev with `scp` per DEVELOPMENT.md §7.
- **Access:** LAN-only; Metabase's built-in auth. No external exposure or reverse proxy in v1.
- **Resource budget:** target < 2 GB RAM, < 10 GB disk for first year at current device count.

### Standards compliance (per `Development/DEVELOPMENT.md`)

- Agent: ask before implementing; never commit/push without approval.
- SemVer in `VERSION`; every release noted in `CHANGELOG.md`; tag releases on both remotes.
- Conventional Commits.
- Branches: `master` (prod), `develop` (integration), `feature/*`, `fix/*`, `chore/*`.
- Required project files: `CONTEXT.md`, `CHANGELOG.md`, `VERSION`, `SESSIONS.md`, `TODO.md` (Inbox / Backlog / Completed), `.gitignore`, `.dockerignore`. `PROCESS.md` once we have deploy steps to document.
- Python: PEP 8, 100-char lines, dependencies pinned with `==`.
- Docker: non-root user, healthcheck, no `apt-get`/`curl` in final runtime layer.

---

## 7. Out of Scope (for v1)

- Alerting / paging on thresholds (revisit after dashboards are in use).
- Multi-tenant client logins (clients see exports, not the live UI, in v1).
- Domains beyond patches (see §10 expansion path).
- HA / clustering.
- External exposure / TLS / reverse proxy.

---

## 8. Open Questions

1. **Snapshot cadence** — hourly default; is 15-min worth it for time-series resolution, or is hourly overkill already?
2. **Retention window** — how far back do we need full snapshots before downsampling? 90 days is a guess.
3. **Transitional CSV export** — do we want email/Slack of the existing CSV as a deliverable while the dashboard is being built, or just wait for the dashboard?
4. **Postgres volume layout** — go with bind-mount under `/amr-ch-01_data/ninja-dashboard/postgres-data` (easier backup / inspect) unless you prefer named Docker volume.
5. **Ninja API credentials** — reuse the existing `ClientId` / `ClientSecret` from the PS script, or mint a separate service credential for the dashboard? (Separate is cleaner; one-time Ninja setup.)
6. **Backup target** — defer to "later stage" per your call. Default during build: `/amr-ch-01_data/ninja-dashboard/backups/`.

**Resolved (don't re-ask):**
- Host: `am-ch-01` (10.61.50.28).
- Deploy: Portainer git auto-deploy from this repo.
- Host data path: `/amr-ch-01_data/ninja-dashboard/`.
- Git: private GitHub repo, dual remotes (`origin` chamayer, `a-m-rose` org).
- Stack components: Postgres + Metabase + Python ingest.
- No reverse proxy — raw ports for now.
- Ninja instance: single — `amrose.rmmservice.com`. Schema does not need a multi-instance dimension.

---

## 9. Expansion Path (future domains)

The Ninja API surface confirmed to be available for future ingest modules — each becomes its own `ninja_<domain>` schema:

| Future schema      | Endpoint(s)                                                                  | Use case                                    |
| ------------------ | ---------------------------------------------------------------------------- | ------------------------------------------- |
| `ninja_tickets`    | `/v2/ticketing/ticket`, `/v2/ticketing/ticket/{id}/log-entry`                | Ticket volume, response times, categories   |
| `ninja_alerts`     | `/v2/alerts`, `/v2/device/{id}/alerts`                                       | Active alert dashboards, alert trends       |
| `ninja_jobs`       | `/v2/jobs`, `/v2/device/{id}/jobs`                                           | Running job visibility, failure rates       |
| `ninja_antivirus`  | `/v2/queries/antivirus-status`, `/v2/queries/antivirus-threats`              | AV coverage, threats detected               |
| `ninja_backups`    | `/v2/backup/jobs`, `/v2/queries/backup/usage`                                | Backup success %, storage usage trends      |
| `ninja_disks`      | `/v2/queries/disks`, `/v2/queries/volumes`, `/v2/queries/raid-*`             | Disk health, SMART, capacity warnings       |
| `ninja_software`   | `/v2/queries/software`, `/v2/queries/software-patches`, `/v2/queries/software-patch-installs` | 3rd-party software inventory + patch state |
| `ninja_hardware`   | `/v2/queries/computer-systems`, `/v2/queries/processors`, `/v2/queries/network-interfaces` | Asset / hardware refresh reports            |
| `ninja_warranty`   | `references.warranty` (already on `/v2/devices-detailed`)                    | Warranty expiration calendar                |
| `ninja_users`      | `/v2/queries/logged-on-users`                                                | Active user reports                         |
| `ninja_windows`    | `/v2/queries/windows-services`                                               | Service status / failed services            |

Each future domain reuses the `ninja_core` lookups and `run_log`; no shared-table changes required.

**Note on activities:** `ninja_activities` is shipped in v1 (filtered to patch-management events only). Future domains that want activity context (alerts, jobs, tickets) extend the filter via `INGEST_ACTIVITY_SOURCES` rather than getting their own private activity tables.

---

## 10. Proposed Build Order

1. **Project scaffold** — required project files per DEVELOPMENT.md (`CONTEXT.md`, `CHANGELOG.md`, `VERSION=0.1.0`, `SESSIONS.md`, `TODO.md`, `.gitignore`, `.dockerignore`).
2. **Docker compose skeleton** — `postgres` + `metabase` only, schema not yet applied. Verify Metabase comes up and connects to Postgres locally (WSL2).
3. **Python ingest container** — `Dockerfile`, `requirements.txt` (pinned), config from env, structured logging.
4. **Migrations + `ninja_core`** — `sql/migrations/001_init.sql` with the `ninja_core` schema above. Ingest applies migrations on startup.
5. **Core ingest** — fetch orgs / locations / policies / devices / custom field definitions + values. Verify row counts match the PowerShell CSV. Write to `run_log`.
6. **Patches ingest** — `sql/migrations/002_patches.sql` adds `ninja_patches`. Ingest module pulls both patch endpoints into `patch_facts` (SCD-2 / hash-dedup).
7. **Activities ingest** — `sql/migrations/003_activities.sql` adds `ninja_activities` and `ninja_core.ingest_state`. Filtered to patch-application + lifecycle events. Incremental via `activities.last_id` cursor.
8. **Scheduler + retries** — APScheduler hourly trigger, exponential backoff on API errors, manual-trigger HTTP endpoint. No run-on-startup unless last scheduled run was missed (catch-up via `run_log` check).
9. **Metabase dashboards (manual)** — Overview + Filterable Detail, with activity enrichment in per-device drilldowns. Build interactively; export dashboard JSON to repo later.
10. **Snapshot accumulation + Trends dashboard** — once a week or two of snapshots exist.
11. **Backups + hardening** — `backup-db.sh`, secrets review, rotate Ninja credentials, deploy to `am-ch-01`.
