# TODO

Per `Development/DEVELOPMENT.md` §0.4: Inbox / Backlog / Completed.
Read Inbox at the start of every session.

---

## Inbox

_(empty — drop free-form items here)_

---

## Backlog

### Ingest core (next milestone — gets us to a working v0.2.0)

- [ ] `ingest/config.py` — pydantic-settings loading `NINJA_*`,
      `POSTGRES_*`, `INGEST_*`. Fail loudly on missing required vars.
      (Done in v0.1.0 scaffold; revisit if env shape changes.)
- [ ] `ingest/core/organizations.py` — fetch all, upsert into
      `ninja_core.organizations`.
- [ ] `ingest/core/locations.py` — fetch all, upsert.
- [ ] `ingest/core/policies.py` — fetch all, upsert.
- [ ] `ingest/core/devices.py` — fetch via `/devices-detailed`, upsert
      into `ninja_core.devices`, write `device_snapshots` row per
      device per run. Confirm where `needs_reboot_reasons` actually
      live in the API response (may be nested in `os.*`, may require a
      second call to `/v2/queries/device-health`). Populate
      `needs_reboot_reasons text[]` accordingly.
- [ ] `ingest/core/custom_fields.py` — fetch definitions + values,
      upsert, regenerate `v_<entity>_custom_fields` pivoted views.
- [ ] `ingest/patches/ingest.py` — fetch `/queries/os-patch-installs`
      and `/queries/os-patches`, SCD-2 / hash-dedup upsert into
      `ninja_patches.patch_facts`.
- [ ] `ingest/activities/ingest.py` — fetch `/v2/activities`,
      server-side filter by `sourceName` (PATCH_MANAGEMENT + SYSTEM),
      client-side allowlist on `activityType`, incremental via
      `ninja_core.ingest_state` key `activities.last_id`. First run
      backfills last 7 days.
- [ ] Wire `run_log` writes (start row, update on completion / error).
- [ ] APScheduler in `ingest/main.py` — hourly default, configurable
      via `INGEST_SCHEDULE_HOURS`.
- [ ] HTTP endpoint for manual trigger (`/run`) + healthcheck
      (`/healthz`).
- [ ] Verify row counts match the existing PowerShell CSV against a
      real Ninja instance.

### Dashboards (after ingest is producing data)

- [ ] Configure Metabase data source: read-only Postgres user.
- [ ] Overview dashboard: total devices, pending, failed, compliance %,
      status donut, by-org bar, by-OS bar, offline > 7d, needs reboot.
- [ ] Filterable Detail dashboard: patch table + per-org +
      per-device drilldown. Filters include custom-field columns from
      the pivoted views. Per-device drilldown shows activity log
      sidebar (joined `ninja_activities.activities` by `device_id`,
      time-windowed).
- [ ] "Patches installed awaiting reboot" panel — join
      `patch_facts` (INSTALLED) with latest
      `device_snapshots.needs_reboot=true` and absence of
      `SYSTEM_REBOOTED` activity since install.
- [ ] Trends dashboard (after ~2 weeks of snapshots): pending over
      time, installs/week, failed over time, compliance % trend.
- [ ] Export dashboard JSON to repo (`metabase/dashboards/`) for
      version control.

### Ops / hardening

- [ ] `backup-db.sh` — nightly `pg_dump` of `ninja` DB to
      `/amr-ch-01_data/ninja-dashboard/backups/`, 14-day retention.
- [ ] `PROCESS.md` — host setup steps, first deploy, secrets
      provisioning, Metabase initial admin.
- [ ] Rotate the Ninja `ClientId` / `ClientSecret` currently hardcoded
      in `Ninja-Patching-report.ps1` once Python ingest is in
      production. The PS script can be left with the old creds until
      it's retired.
- [ ] Mint a dedicated Ninja API service credential for the dashboard
      (separate from any admin script credential). One-time Ninja-side
      setup.

### Schema / data

- [ ] Snapshot retention job — drop `device_snapshots` older than 90
      days to daily granularity (defer; needs operator input on
      retention). SCD-2 tables (`patch_facts`,
      `custom_field_values`) don't need pruning — the whole history is
      the point.
- [ ] Decide cadence: stay at hourly or move to 15-min for tighter
      trends. Defer to operator feedback after first month.
- [ ] Address `references.warranty` data — present on
      `/devices-detailed`, not yet surfaced. Asset/warranty domain
      candidate.

### Open questions to resolve (from `REQUIREMENTS.md` §8)

- [ ] Snapshot cadence — confirm hourly or shift to 15 min.
- [ ] Snapshot retention window — 90 days then downsample? operator
      call.
- [ ] Transitional CSV email/Slack while dashboard is being built? Or
      wait for the dashboard?
- [ ] Ninja API credentials — reuse existing or mint new service cred?

---

## Completed

### v0.1.0 — 2026-06-02

- [x] Project design & decisions captured in `REQUIREMENTS.md`.
- [x] Repo scaffold: `CONTEXT.md`, `CHANGELOG.md`, `VERSION`,
      `SESSIONS.md`, `TODO.md`, `.gitignore`, `.dockerignore`.
- [x] `docker-compose.yml` (postgres + metabase + ingest), `Dockerfile`,
      `requirements.txt`, `.env.example`.
- [x] `ingest/` Python package skeleton.
- [x] `sql/init/00_create_databases.sh` — Postgres bootstrap.
- [x] `sql/migrations/001_init_core.sql` — `ninja_core` schema.
- [x] `sql/migrations/002_patches.sql` — `ninja_patches.patch_facts`.
- [x] SCD-2 / content-hash dedup baked into `patch_facts` and
      `custom_field_values` from the start (not deferred).
- [x] Scheduler clarified: no run-on-startup unless last scheduled
      run was missed (catch-up via `run_log` check).
- [x] `activities` domain added to v1 scope:
      `sql/migrations/003_activities.sql` (ninja_core.ingest_state +
      ninja_activities.activities), `ingest/activities/` package
      skeleton. Filter: PATCH_MANAGEMENT lifecycle events +
      SYSTEM_REBOOTED.
- [x] Tightened published-port surface: only Metabase on LAN;
      ingest on loopback; Postgres internal-only.
- [x] `PORTS.md` documents host port map + what this stack publishes.
- [x] `ingest/ninja_client.py` — full implementation: OAuth2 token
      lifecycle, retry/backoff on 5xx/429, refresh-and-retry on 401,
      `paginate_after` + `paginate_cursor`, sync `httpx.Client`.
- [x] `ingest/db.py` — psycopg-pool `ConnectionPool`, `transaction()`
      context, generic `upsert()` helper using `psycopg.sql` for safe
      identifier composition.
- [x] `ingest/migrations.py` — discovery + bootstrap handling of
      first-run `UndefinedTable` for `schema_migrations`.
- [x] `ingest/smoke.py` — `python -m ingest.smoke` verifies env,
      Postgres connectivity, applies pending migrations, Ninja auth,
      and one `/organizations` call. Non-zero exit on any failure.
- [x] Added `psycopg-pool==3.2.3` to `requirements.txt`.
- [x] Env handling settled on bind-mount + read-at-start (dmarc
      pattern). ingest uses python-dotenv on `/app/.env`; postgres
      and metabase wrap their entrypoints to `source /etc/secrets.env`
      before exec'ing the real entrypoint. Single source of truth on
      host: `/amr-ch-01_data/ninja-dashboard/.env`. Sidesteps
      Portainer's git-mode limits on `${VAR}` and `env_file:` with
      absolute paths.
- [x] `docker-compose.yml` switched from `${VAR}` substitution to
      `env_file: /amr-ch-01_data/ninja-dashboard/.env` on each service.
      Host `.env` is now the single source of truth — no Portainer-side
      env config required. Static values (POSTGRES_HOST=postgres,
      MB_DB_TYPE=postgres, etc.) stay in `environment:` so they can't
      be wrongly overridden.
