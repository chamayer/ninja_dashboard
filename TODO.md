# TODO

Per `Development/DEVELOPMENT.md` §0.4: Inbox / Backlog / Completed.
Read Inbox at the start of every session.

---

## Inbox

- [ ] After v0.34.2 deploys, run the Metabase bootstrap and validate
      Command Center / Client Patch Status / Triage page load times,
      dashboard filters, and click-through paths for client, device,
      patch state, KB, device type, and message search.
- [ ] After v0.32.0 redeploys, run `/run/agent-compliance` and
      execute the new validation queries (HANDY_COMMANDS.md
      "id-link sanity") to confirm no
      `(platform, platform_group_id)` maps to multiple client_ids.
- [ ] SC session `YLSedison` (UTA, session id
      `f2499b9f-0ff7-4fb9-a336-45f0008e31a8`) has empty `GuestInfo`
      so it does not collapse with the `NJ3` device that Ninja now
      reports. Operator action: either rename the SC session to
      `NJ3` in the SC console, or uninstall + reinstall the SC
      client on the box using the standard installer (not a
      pre-named one) so SC captures `MachineName=NJ3` on
      registration. Not a code task.

---

## Backlog

### Ingest domain split

- [ ] Split the ingest runtime into domain packages with explicit
      entrypoints for patching, compliance, and inventory. v0.33.0
      adds the Inventory package and standalone Metabase bootstrap, but
      the shared service still owns scheduling and startup orchestration.
      Next step: extract shared scheduler/bootstrap plumbing and move
      patch/compliance entrypoints behind the same domain boundary.

### Agent compliance domain

- [ ] **Per-OS required_platforms overrides.** Macs (and Linux)
      currently inherit the client's full `[Ninja, SentinelOne,
      LogMeIn]` requirement. LogMeIn likely isn't on Macs by policy,
      so they show as Missing forever. Add an OS-aware overlay to
      the requirements model: either a `platform_requirements` row
      keyed by `(client_id, device_scope, os_family_pattern)` or a
      `required_platforms_by_os` jsonb on `clients`. Shipped
      alongside v0.30.0 (`051_agent_compliance_unresolved_and_macos.sql`)
      where macOS / Linux became visible in `os_family`.

- [ ] **Linux distro split in `os_family`.** v0.30.0 lumps all
      Linux variants (Ubuntu, CentOS, Debian, RHEL, etc.) into a
      single `Linux` bucket. Operators may want distro-level
      breakdown for patch cadence and agent compatibility reasons.
      Cheap to add as a CASE expansion in `v_device_state_current`.



- [ ] **First end-to-end alert** — pick one finding type (e.g.
      `missing_required_platform` for a known noncompliant device),
      enable a notification route in
      `ninja_agent_compliance.notification_routes` (webhook is the
      lowest-friction), set the corresponding host `.env` secret,
      trigger `/run/agent-compliance`, and confirm the alert
      dispatcher records a send in `alert_events`.

- [ ] **Alias gap audit (DJ-UTAH class)** — run the diagnostic
      SELECT from the v0.19.0 design notes, diff the unresolved /
      discovered-as-client rows against the PowerShell `$OrgConfig`
      table, and seed the missing aliases in one migration. Plus:
      audit `config_loader.py` alias matching for case sensitivity
      (`DJ-Utah` vs `DJ-UTAH`) and trim/punctuation normalization.

- [ ] Live-validate v0.19.0 on the stack: redeploy ingest, run
      `/run/agent-compliance`, bootstrap Metabase, verify section
      headers render, Customer filter scopes every card on Devices,
      `State = Degraded` matches rows, `NO AV = Yes` matches rows for
      policy-exempt devices, device drilldown click-through works,
      and `Age 7d` / `30d` / `90d` writes through without changing
      the platform combo.

### Drilldown follow-ups (v0.19.0 baseline → future polish)

- [ ] Add a "pick a device" hint card on the drilldown dashboard so
      the experience isn't empty when reached directly (today the
      cards just show no rows). Could be a `Need action` mini-table
      that link-targets the drilldown.
- [ ] Per-platform observation timeline — surface
      `platform_observations` events as a sparse log alongside the
      matrix snapshots, so the operator can see exactly when Ninja
      stopped reporting vs S1 etc.
- [ ] Compliance-state sparkline / day rollup — easier to scan than
      the per-run matrix snapshot for devices with many history
      rows.
- [ ] Drilldown alias match: support `?norm=...` URL param in
      addition to `?host=...` so suppression history joins by
      `norm_name` for devices whose display name has changed over
      time.

### Operator UI follow-ups exposed by v0.19.0

- [ ] **Enable / disable sources from the UI.** Today it's psql.
      A Health-dashboard action column would cut friction for the
      one-off cases (rotating an S1 key, pausing LMI during
      maintenance).
- [ ] **New canonical customer endpoint (`/a/nc`)** — the discovery
      flow handles 99% of cases, but pre-seeding a customer before
      onboarding is psql-only today. Low priority; revisit if it
      starts happening regularly.
- [ ] **Drop or keep `Cross-customer conflict` long-term.** Demoted
      to Debug in v0.19.0; revisit after a month of live data — if
      it never surfaces anything actionable, drop the card and the
      view entirely.

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
- [x] `ingest/core/custom_fields.py` — fetch scoped values from
      `/queries/scoped-custom-fields`, filter by
      `INGEST_CUSTOM_FIELDS_INCLUDE`, SCD-2 upsert values, regenerate
      `v_<entity>_custom_fields` pivoted views for device / org /
      location scopes.
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
- [x] Overview dashboard: total devices, pending, failed, compliance %,
      status donut, by-org bar, by-OS bar, offline > 7d, needs reboot.
- [x] Patch Command Center: top-level operator workflow with client,
      failed patch, manual/delayed, stale patching, never-patched, and
      reboot queues.
- [x] Org Overview dashboard: org-scoped action page with client KPIs,
      failed patch queue, manual/delayed queue, stale/never-patched
      device queue, OS-family rollups, and reboot attention.
- [ ] Filterable Detail dashboard: patch table + per-org +
      per-device drilldown. Filters include custom-field columns from
      the pivoted views. Per-device drilldown shows activity log
      sidebar (joined `ninja_activities.activities` by `device_id`,
      time-windowed).
- [ ] Custom-field exception wiring: surface
      `patchingDisabled`, `serverPatchingDisabled`,
      `workstationPatchingDisabled`, and `patchingNotes` in the detail
      dashboards and filters with device-over-org precedence. Ingest
      is now wired; UI wiring remains.
- [ ] "Patches installed awaiting reboot" panel — join
      `patch_facts` (INSTALLED) with latest
      `device_snapshots.needs_reboot=true` and absence of
      `SYSTEM_REBOOTED` activity since install.
- [ ] Trends dashboard (after ~2 weeks of snapshots): pending over
      time, installs/week, failed over time, compliance % trend.
- [ ] Export dashboard JSON to repo (`metabase/dashboards/`) for
      version control.

### Permanently parked (do not revisit)

- **Activity `user_id` in dashboards** — Ninja's `userId` on activity
  records is internal audit (which Ninja API user/service triggered
  the event), not the device's logged-in user or the MSP technician.
  No business value. The column stays in the schema because removing
  it is more disruption than benefit; **do NOT surface it in
  dashboards, do NOT add a user-name lookup, do NOT bring it up
  again.**

- **Separate `device_aliases` mapping table** — superseded by
  `human_decisions.decision_type = 'same_device'` in v0.32.9. Device
  name merges are real operator decisions, but they stay in the shared
  decision table instead of a new alias subsystem.

- **Per-platform aliases as a rename-mitigation mechanism** —
  superseded by `client_platform_links` (id-link table, v0.32.0).
  Aliases stay only for cross-platform identity glue. Adding alias
  rows to fix a rename inside a single platform is the wrong layer.
  **Do NOT re-propose; the id-link makes it unnecessary.**

### Active priority

- [x] **Activities ingest** — done in 0.6.0.

### Ops / hardening (backlog)

- [ ] Stale-data banner — if `v_active_devices` returns 0 (because
      ingest broke), dashboards look empty. A markdown card at the
      top of Overview showing `MAX(last_observed_at)` from run_log
      would tell the operator at a glance.
- [ ] Promote `postgres-data` (and possibly `metabase-data`) to
      `external: true` named volumes once there's real data worth
      protecting. Today they're auto-managed — survive normal stack
      ops but get destroyed by explicit "remove stack WITH volumes"
      or `docker compose down -v`. External requires pre-creating
      the volumes with `docker volume create` but won't auto-delete.
      Bumped in priority 2026-06-17: Metabase public-share link UUIDs
      live in the `metabase_app` DB on `postgres-data`. If the volume
      is nuked, every shared URL dies and the team has to be re-sent
      new links. Worth doing before we hand more public links out.
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

### Parked (revisit later)

- [ ] **Patch age / waiting time surface.** Currently no UI signal for
      how long a patch has been sitting in MANUAL or DELAYED.
      Constraint: Ninja API exposes no release date or
      first-discovered timestamp on patches — confirmed against
      `NinjaRMM-API-v2_formatted.json` (all 4 patch endpoints return
      only id, name, severity, status, type, kbNumber, +/- timestamps
      tied to data collection or install attempt). What we *can* use:
      `patch_facts.first_observed_at` (= how long in our DB). For real
      release dates, would need external enrichment via `kbNumber` →
      MSRC / Microsoft Update Catalog. Park until there's operator
      demand strong enough to justify the enrichment work.

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

### v0.16.0 — 2026-06-10

- [x] Built Agent Compliance v1 foundation inside this project:
      schema/config tables, source runs, platform observations,
      current/history matrix, findings, suppressions, alert state,
      webhook/email/Zendesk alert delivery, per-client ScreenConnect
      source model, separate schedule/manual endpoint, and basic
      Metabase dashboard bootstrap. Compile passed; live DB smoke
      remains pending.

### v0.14.10 — 2026-06-04

- [x] Aligned Org Overview and Trends KPI labels to
      `Fully patched % (patching devices)`. Commit `be63e7e`.

### v0.14.9 — 2026-06-04

- [x] Renamed the second patch KPI to
      `Fully patched % (patching devices)` and updated the formula to
      use the patching-device subset. Commit `148de4e`.

### v0.14.8 — 2026-06-04

- [x] Fixed the active-patching KPI bootstrap so
      `ingest/metabase_bootstrap.py` imports cleanly again.
      Commit `ba55729`.

### v0.14.7 — 2026-06-04

- [x] Split the operator dashboard KPIs into `Actively patching %`
      and `Fully patched devices %`, while keeping the Command Center
      count cards. Commit `52c22e6`.

### v0.14.6 — 2026-06-04

- [x] Split the dashboard compliance story into
      `Devices Compliant %` and `Patch Progress %` across Command
      Center, Overall Status, Org Overview, and Trends.
      Commit `fafe234`.

### v0.14.4 — 2026-06-04

- [x] Metabase card reuse stopped by moving bootstrap identity from
      visible title to hidden stable UID in card `description`.
      Commit `2779967`.

### v0.10.0 — 2026-06-03

- [x] Added **Ninja — Patch Command Center** as the top-level patch
      operator landing dashboard.
- [x] Rebuilt **Ninja — Org Overview** into an actionable client page
      instead of a decorative summary.
- [x] Changed OS dashboard filters to OS families:
      Windows 11, Windows 10, Windows Server, Other Windows, Unknown.
- [x] Replaced visible technical labels with operator-facing
      terminology such as Device Type, Operating System, Patching
      Status, Install Results, Failed Patches, Stale Patching, and
      Never Patched.

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
