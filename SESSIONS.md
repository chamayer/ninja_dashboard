# Sessions

Chronological dev journal. What was done each session, why decisions
were made, what's pending. Useful for resuming interrupted work.

---

## 2026-06-03 — v0.11.2 per-column click_behavior moved to dashcard

**Why:** After v0.11.1, user tested and reported:
- Compliance numbers fixed ✓
- Whole-card bar chart click works (compliance_worst) ✓
- All per-column table clicks STILL show the default filter popup ✗
  (compliance_all, needs_reboot, cmd_clients)

**Diagnosis:** Whole-card click_behavior at the card level works;
per-column click_behavior at the card level is silently ignored by
this Metabase version. Per-column behaviors only take effect when
written to the **dashcard's** visualization_settings.

**Done:**
- Extracted `_build_column_settings_for_dashcard` helper that
  computes the column_settings dict from a card spec.
- Modified `_set_dashboard_layout` to accept `dash_id_by_name` and,
  when provided, build per-card column_settings and inline them into
  each dashcard's `visualization_settings`.
- Pass 1b now passes `dash_id_by_name` to layout, so click target
  IDs resolve correctly during the dashboard PUT.
- Pass 2 (apply_click_behaviors at card level) is unchanged. The
  per-column writes there are now harmless no-ops; left in place so
  card-level whole-card click_behavior continues to work.

**Validation:**
- `python -m py_compile` passes.
- Pending operator verify after Portainer rebuild.

## 2026-06-03 — v0.11.1 compliance + click-thru fixes

**Done:**
- Fixed compliance numbers showing 0 % everywhere. Root cause:
  `current_state` CTEs filtered to `fact_type='patch_state'` (the
  pending/failed side); INSTALLED rows live in
  `fact_type='install_outcome'`. The query never had any rows to
  count as installed, so the numerator was always 0. Rewrote
  `compliance_worst`, `compliance_all`, and `org_compliance` to
  compute installed count from install_outcome over the universe
  of all (device, patch) pairs.
- Fixed Fleet Overview table click-thrus by applying the v0.10.2
  source-alias lesson (lowercase, snake_case, unquoted) to
  `Client Patch Compliance` and `Devices Needing Reboot`. Both
  tables had been built with `o.name AS "Organization"` /
  `d.system_name AS "Device"` / `{DEVICE_TYPE_D} AS "Device Type"`
  with column_click_behaviors keyed on the same quoted strings —
  Metabase's per-column click_behavior is fussy about this.
- Added the missing `Patching Devices` scalar to Patch Command
  Center so the device-state triple is consistent with Fleet
  Overview.

**Pending diagnosis:**
- User reported that the `Clients Needing Attention` org-name
  click on Command Center doesn't navigate. cmd_clients already
  uses the v0.10.2 lowercase pattern, so v0.11.1 shouldn't change
  its behavior. Awaiting post-deploy retest — if it's still
  broken after the Portainer rebuild picks up the bootstrap pass,
  we'll inspect the live Metabase parameterMapping JSON.

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Spot-checked the three rewritten compliance queries: numerator
  references `installed_patches.device_id` (which only contains
  install_outcome=INSTALLED), denominator from `all_patches`
  (DISTINCT over the entire patch_facts table).

## 2026-06-03 — v0.11.0 nav bar + terminology consolidation

**Done:**
- Added a cross-dashboard nav bar (Metabase virtual text dashcard)
  to all 6 dashboards. Bolds the current dashboard, links to the
  rest. Implemented via `card_id: null` + `visualization_settings.
  virtual_card` and a new `_build_nav_markdown` helper.
- Restructured `run_bootstrap` into 3 passes so dashboard layouts
  (which now need the nav bar to resolve sibling dashboard URLs)
  run after all dashboard IDs are collected.
- `_set_dashboard_layout` gained an optional `nav_markdown`
  parameter that prepends the nav and shifts other cards down by
  `NAV_HEIGHT` — keeps card specs free of layout offset math.
- Terminology pass per operator review:
  - Patch state pie cards (lived on 4 dashboards) renamed from
    "Patching Status" to "Current Patch State" to free up "Patching
    Status" for the PCOV concept exclusively.
  - PCOV "Patch Activity" column/filter/cards renamed to "Patching
    Status" so dashboard name and contents agree.
  - Device-state triple is now unambiguously about devices:
    "Patching Devices / Stalled Devices / Never-Patched Devices"
    (replaces "Recent Patch Activity / Stale Patching / Never
    Patched"). The old labels read as patch states, not device
    states.
  - Fleet Overview's lumped "Manual / Delayed" scalar split into two
    scalars matching Command Center and Org Overview.
  - "Delayed Install" → "Delayed Patches"; "Approved Windows
    Devices" → "Active Devices".

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Spot-checked all card "name" lines — no remaining "Stale Patching",
  "Never Patched" (bare), or "Recent Patch Activity" labels;
  DASH_PCOV value still intact.

**Honest caveat:**
- This is the first time virtual text dashcards have been provisioned
  via API in this codebase. The JSON shape (`card_id: null` +
  `visualization_settings.virtual_card`) comes from Metabase API
  docs and is consistent with public references, but it's untested
  on the live Metabase here. If the layout PUT 4xx's on first
  bootstrap after redeploy, that's where to look first.

## 2026-06-03 — v0.10.2 Command Center org click fix

**Done:**
- Investigated **Clients Needing Attention** on **Ninja — Patch
  Command Center** where clicking a client name did nothing.
- Restored the stable lowercase `organization` SQL alias and click
  source for that table. Metabase's per-column click behavior is more
  reliable with stable source column names than with quoted display
  aliases containing spaces/capitalization.
- Clarified mixed-unit columns in attention/status tables: patch counts
  now say `Patches`, and device counts now say `Devices`.
- Shortened the visible dashboard label from `Active Windows Devices`
  to `Active Devices`; the underlying dashboard population remains
  Windows-only.

**Validation:**
- `python -m compileall ingest` passes.
- Dashboard definition check confirms the card maps the
  `organization` column to **Ninja — Org Overview** with `p_org`.

## 2026-06-03 — v0.10.1 stale patching threshold

**Done:**
- Clarified that **Stale Patching** is a device count: devices with at
  least one install/attempt timestamp, but whose latest install/attempt
  is older than the stale threshold.
- Changed the stale threshold default from 7 days to 35 days because
  patching commonly runs weekly at best and often monthly.
- Replaced hard-coded 7-day thresholds in Command Center, Overview, and
  Org Overview with the shared `DEFAULT_STALE_PATCH_DAYS = 35`.
- Updated **Ninja — Patching Status** so the dashboard-level `Stale
  threshold (days)` filter also defaults to 35 while remaining
  operator-changeable.

**Validation:**
- Built dashboard definitions and confirmed no emitted SQL contains
  `INTERVAL '7 days'` or the literal Python constant name.

## 2026-06-03 — v0.10.0 Patch Command Center + dashboard terminology

**Done:**
- Added **Ninja — Patch Command Center** as the top-level workflow
  dashboard for patch operators. It brings together the fleet-wide
  work queues: clients needing attention, failed patch queue,
  manual/delayed patches, stale patching, never-patched devices, and
  reboot attention.
- Rebuilt **Ninja — Org Overview** from a summary-style dashboard into
  an org-scoped action page. It now answers what is happening for one
  client and what needs work next, with direct drills to Device
  Drilldown, Patch Detail, and Patching Status.
- Reviewed dashboard terminology and replaced raw/technical labels
  with operator-facing terms:
  `Active Devices`, `Approved Patches`, `Manual Approval`,
  `Delayed Install`, `Failed Patches`, `Recent Patch Activity`,
  `Stale Patching`, `Never Patched`, `Device Type`,
  `Operating System`, `Patching Status`, and `Install Results`.
- Changed OS filters from exact OS names to OS-family choices:
  `Windows 11`, `Windows 10`, `Windows Server`, `Other Windows`, and
  `Unknown`. Detail/drilldown tables still show the exact operating
  system string where that level of detail is useful.
- Changed Device Type filters to readable values (`Windows
  Workstation`, `Windows Server`) while keeping the underlying Ninja
  node-class values internal.
- URL-encoded scalar-card drill link presets so human labels with
  spaces work as dashboard filter values.

**Validation:**
- `python -m compileall ingest` passes.
- Dashboard definitions build to six dashboards with expected card
  counts when dependency modules are stubbed:
  Command Center 12, Overview 12, Org Overview 15, Patch Detail 8,
  Device Drilldown 5, Patching Status 9.
- A direct import check in the workstation Python failed because
  `httpx` is not installed locally; the stubbed build check validated
  the dashboard specs without installing dependencies.
- Live Metabase bootstrap still needs to run in the deployed ingest
  container to apply the dashboard updates.

**Process:**
- This was treated as a significant dashboard rebuild and was
  implemented only after explicit user approval.

## 2026-06-03 — v0.9.0 patch fact typing + stale timeframe

**Done:**
- Investigated why **Stale Patch Data** could show `0`.
- Agreed that Patching Status should be based on the latest available
  install/attempt time for a device, not Ninja's observation timestamp
  and not our ingest timestamp.
- Added `patch_facts.fact_type` to distinguish
  `/queries/os-patches` state rows from `/queries/os-patch-installs`
  install-outcome rows. Historical rows are backfilled by status in
  migration `006_patch_fact_type.sql`; future ingest stamps source
  semantics directly.
- Changed Patching Status classification to use
  `MAX(installed_at)` from `fact_type = 'install_outcome'` rows.
- Kept the existing `Stale threshold (days)` dashboard filter as the
  timeframe control for active vs stale patching status.
- Updated failed-install and no-patch-data dashboard queries to use
  `fact_type = 'install_outcome'` instead of inferring source from
  status values.

**Validation:**
- `python -m compileall ingest` passes.
- Live Metabase bootstrap still needs to be re-run to apply the card
  SQL update.

**Process:**
- Updated `Development/DEVELOPMENT.md` to require explicit approval
  before significant rewrites unless the user overrides that rule for
  the current task.

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
