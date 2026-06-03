# Sessions

Chronological dev journal. What was done each session, why decisions
were made, what's pending. Useful for resuming interrupted work.

---

## 2026-06-03 — v0.8.1 current state vs install outcome

**Done:**
- Investigated a real Postgres example where the same
  `(device_id, patch_uid)` had:
  - current patch state row: `APPROVED`
  - latest install outcome row: `FAILED`
- Confirmed the old dashboard SQL was counting only the latest mixed
  `patch_facts` row, so a newer `APPROVED` state hid the failed
  install attempt.
- Added a separate latest-install-outcome CTE to the Metabase
  bootstrap SQL, ordered deterministically by `installed_at`,
  `ninja_observed_at`, `last_observed_at`, then `id`.
- Updated Fleet and Org **Failed Installs** cards to count latest
  install outcome, not current state.
- Added an **Install Outcome** filter to Patch Detail and kept
  **Status** as the current patch-state filter.
- Updated Patch Detail table to show both `current_status` and
  `last_install_outcome`, plus `last_install_at`.
- Updated Org Top Problem Patches to prioritize latest failed install
  outcomes while still surfacing current queued patches.

**Validation:**
- `python -m compileall ingest` passes.
- Live Metabase bootstrap still needs to be re-run to apply the SQL
  changes to cards.

**Decision:**
- Dashboard labels now intentionally distinguish state from outcome:
  `APPROVED`, `MANUAL`, `DELAYED` are current patch states;
  `FAILED` and `INSTALLED` are install outcomes.

## 2026-06-03 — v0.8.0 Org Overview + patching status model

**Done:**
- Picked up from Claude's dashboard-design conversation and carried the
  agreed operator model into the Metabase bootstrap:
  Fleet Overview → Org Overview → Device Drilldown, with Patch Detail
  kept as the flat filterable work list.
- Added **Ninja — Org Overview** with org-scoped cards for patch
  compliance, active Windows devices, not-being-patched count, failed
  installs, ready/manual queues, patch state, Windows class/OS
  compliance, top problem patches, and reboot attention.
- Rewired Fleet Overview org clicks to **Org Overview** instead of
  sending operators straight to Patch Detail.
- Added a Device dropdown to Patch Detail and changed Device Drilldown
  from free-text substring search to exact device selection. Device
  names are populated from `ninja_core.v_active_devices`.
- Renamed **Ninja — Patch Coverage** to **Ninja — Patching Status**.
  Bootstrap now renames the legacy dashboard in place if it already
  exists, rather than creating a duplicate dashboard.
- Scoped patch operator dashboards to Windows patching only:
  `WINDOWS_WORKSTATION` and `WINDOWS_SERVER`.
- Added migration `005_active_windows_devices_view.sql` so already
  deployed databases replace `ninja_core.v_active_devices` even if
  migration `004` was already recorded.
- Updated `CHANGELOG.md`, `VERSION`, `CONTEXT.md`, and `TODO.md`.

**Validation:**
- `python -m compileall ingest` passes.
- Did not run live Metabase bootstrap from this workstation; runtime
  verification still needs to happen against the deployed Metabase API.

**Decisions confirmed:**
- "Overview is overview and details is details": Org Overview is not a
  flat patch list, and Device Drilldown remains a device profile.
- "Patching Status" is the current name for the former Patch Coverage
  concept. It is framed as device patching status, not governance and
  not generic device reporting.
- Non-Windows devices remain in the database but are out of scope for
  v1 patch operator dashboards.

**Pending:**
- Run/re-run Metabase bootstrap after deploy and verify dashboard
  parameters, click behavior, and exact-device dropdown behavior in
  the live Metabase UI.
- If the device dropdown feels slow with the full active fleet, revisit
  a query-backed or text/autocomplete parameter approach.

## 2026-06-02 — Project kickoff & design

**Done:**
- Scoped the project from "patch report dashboard" to "Ninja dashboard
  platform, patches as first domain".
- Decided architecture: Python ingest → Postgres → Metabase, in Docker
  Compose on `am-ch-01`, deployed by Portainer from this repo (same
  pattern as `dmarc`).
- Rejected alternatives with reasoning recorded in `REQUIREMENTS.md`
  §3: live API queries (no history → no time-series), Grafana (clunky
  for relational slicing), custom Flask app (weeks of UI work for
  parity with Metabase OOTB), SQLite (Postgres wins on Metabase
  integration, jsonb, GIN, concurrency at no real cost).
- Extracted NinjaRMM v2 API schemas from the OpenAPI spec to ground
  the Postgres schema in real fields (not guesses).
- Designed `ninja_core` + `ninja_patches` schemas: jsonb on every
  table for raw payloads, `approval_status` first-class on devices,
  custom field EAV with auto-pivoted views, `run_log` with `domain`
  column.
- Scaffolded the repo: docker-compose, Dockerfile, requirements,
  `.env.example`, Python package skeleton, migration SQL.

**Decisions confirmed:**
- Private GitHub repo; dual remotes (`origin` chamayer, `a-m-rose`
  org).
- LAN-only; no reverse proxy on `am-ch-01` yet — raw ports.
- Postgres data via bind-mount under
  `/amr-ch-01_data/ninja-dashboard/postgres-data/`.
- Hourly snapshot cadence as starting default.

**Pending (mirrors `TODO.md` Backlog — see there for authoritative
list):**
- Port the actual Ninja client code from `Ninja-Patching-report.ps1`
  to `ingest/ninja_client.py` (auth, pagination, the two cursor types).
- Implement the core ingest modules (orgs, locations, policies,
  devices, custom fields).
- Implement the patches ingest module.
- APScheduler wiring + manual-trigger HTTP endpoint.
- Test against real Ninja data — verify row counts match the PS CSV.
- Build Overview + Filterable Detail dashboards in Metabase.
- Decide snapshot retention (90 days full → daily downsample?).
- Rotate Ninja API credentials once Python ingest is live.
