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
- [x] `ingest/core/locations.py` — fetch all, upsert.
- [x] `ingest/core/policies.py` — fetch all, upsert.
- [x] `ingest/core/devices.py` — fetch via `/devices-detailed`, upsert
      into `ninja_core.devices`, write `device_snapshots` row per
      device per run. `needs_reboot_reasons` left NULL — confirm
      where it lives (`/v2/queries/device-health`?) and wire later.
- [x] `ingest/core/custom_fields.py` — fetch definitions + values,
      upsert defs, SCD-2 values, regenerate
      `v_<entity>_custom_fields` pivoted views. **Response shape was
      best-guess** — verify against real Ninja data and fix mapping
      if needed.
- [x] `ingest/patches/ingest.py` — both endpoints, SCD-2 / hash-dedup.
- [x] `ingest/activities/ingest.py` — server-side `sourceName` +
      `after` cursor, client-side allowlist, ingest_state for cursor.
      **No backfill** on first run (just sets cursor); backfill is a
      future one-shot script.
- [x] Wire `run_log` writes — via `ingest/runlog.py` context manager
      reused by every module.

### Follow-ups exposed during v1 ingest landing

- [ ] **Two-endpoint custom_fields rewrite (parked from v0.2)** —
      `/v2/custom-fields` returns 118 definitions including their
      `apiPermission`; `/queries/scoped-custom-fields-detailed`
      returns values for the ~19 fields with API permission != NONE.
      Wire both, populate `custom_field_definitions`, expose
      `api_permission` so operators can see which Ninja fields need
      their permission changed to flow through. Requires migration
      `004_custom_field_defs_v2.sql` (new schema, `(entity_type,
      name)` as PK instead of an integer id Ninja doesn't return).
- [ ] **Backfill script for activities.** Operator-triggered one-shot
      that walks `/activities?olderThan=<id>` (or similar) backward
      from the current cursor to populate history. Useful right after
      first deploy.
- [ ] **Wire `needs_reboot_reasons`** from `/v2/queries/device-health`
      (or wherever Windows reboot reasons surface). Currently NULL.
- [ ] **Split SCD-2 counts** — rows_changed (inserts) vs
      rows_observed (total fetched). Currently `db.upsert` returns
      cur.rowcount which lumps inserts + updates. Use `RETURNING xmax`
      or similar to distinguish.
- [ ] APScheduler in `ingest/main.py` — hourly default, configurable
      via `INGEST_SCHEDULE_HOURS`. _(Done — scheduler runs, no jobs
      wired yet)_
- [ ] HTTP endpoint for manual trigger (`/run`) + healthcheck
      (`/healthz`). _(Done — stdlib threading HTTP server on
      INGEST_HTTP_PORT)_
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

- [ ] **Activities ingest fix (priority next)** — `/v2/activities`
      returns a `{lastActivityId, activities}` shape (not the cursor
      model the `/queries/*` endpoints use). Needs a dedicated
      paginator using `?olderThan=<id>` (confirm with probe). Once
      working, unlocks SYSTEM_REBOOTED events + "what happened
      around this patch" enrichment for Device Drilldown.
- [ ] **Move dashboard definitions out of Python into YAML** —
      `dashboards/*.yaml` with a small loader. Defer until either
      more contributors are editing dashboards or we have >10
      dashboards. Single contributor + 4 dashboards doesn't justify
      the refactor today.
- [ ] **Split `metabase_bootstrap.py`** — approaching 1500 lines.
      `metabase_bootstrap/{cards,dashboards,client,clickbehavior}.py`.
      Pure refactor, no behavior change.
- [ ] **Stale-data banner** — if `v_active_devices` returns 0 (because
      ingest broke), dashboards look empty. A markdown card at the
      top of Overview showing `MAX(last_observed_at)` from run_log
      would tell the operator at a glance.
- [ ] Promote `postgres-data` (and possibly `metabase-data`) to
      `external: true` named volumes once there's real data worth
      protecting. Today they're auto-managed — survive normal stack
      ops but get destroyed by explicit "remove stack WITH volumes"
      or `docker compose down -v`. External requires pre-creating
      the volumes with `docker volume create` but won't auto-delete.
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
