# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [0.15.1] — 2026-06-07

### Added
- **Per-device warning + failure + scan rollups on
  `device_activity_signal`** (migration 017). Three new column
  groups, all driven from existing activity rows so no re-ingest
  needed:
  - Warning rollup: `last_warning_at`, `warning_events`,
    `warning_events_30d`, `last_warning_message` — aggregates
    `PATCH_MANAGEMENT_MESSAGE` + `SOFTWARE_PATCH_MANAGEMENT_MESSAGE`
    rows per device.
  - Failure 30d window: `patch_failure_events_30d` joins the
    existing `patch_failure_events` lifetime count.
  - Scan rollup: `last_scan_started`, `last_scan_completed`,
    `first_scan_started`, `scan_events_30d` — answers "when did
    Ninja first / last scan this device?" without per-card
    aggregation.
  - All surfaced on `device_troubleshooting_signal` for
    Issues / Drilldown re-use.
- **Device Drilldown Device Summary** now shows `First Managed`,
  `Last Scan`, `Last Warning`, `Warnings (30d)`, `Failures (30d)`
  columns alongside the existing health/contact fields.
- **Device Drilldown `Recent OS Patch Warnings (30d)` table** —
  one row per warning event with a `Category` column that hand-
  classifies the 7 dominant message patterns we see in real data
  (outstanding approved patches, scheduled job skipped, metered
  connection, post-reboot scan required, OS patch download error,
  reboot needed, WUA out of date) plus `Other` / `Reboot
  scheduling` / `Download complete` buckets.
- **Device Drilldown `Recent OS Patch Failures (30d)` table** —
  same shape, classified by Ninja error code (-3005 / -3004 /
  -1001) plus common service-level signatures.
- **Issues `Issue Queue` table** gains `Warnings 30d`,
  `Failures 30d`, and `Days Since Warning` columns. Sort order
  now bumps devices with active warnings or failures above
  manual approvals.
- **Issues `Warnings by Category (30d)` card** — fleet-wide
  table of warning events grouped by category, with device count
  per category. Respects the dashboard org filter.
- **Issues `Failures by Error Code (30d)` card** — same shape
  for failures.

### Notes
- Migration 017 drop+recreates both `device_activity_signal` and
  the dependent `device_troubleshooting_signal` (full body
  duplicated from migration 016 with new columns added). Same
  refresh strategy as before — no `main.py` changes needed.
- Category classification lives in dashboard SQL (CASE WHEN over
  message text), not in the MV. Tweaking categories doesn't
  require a migration.
- Commit: `TBD`

## [0.15.0] — 2026-06-05

### Fixed
- **Never-Patched misclassification for devices with install rows but
  no `installedAt`.** Ninja's `/queries/os-patch-installs` omits the
  install timestamp for ~1.2% of INSTALLED rows (typically old or
  OS-applied historical patches). The `device_patch_signal`
  materialized view previously filtered `installed_at IS NOT NULL` at
  source, dropping ~6 devices from the signal entirely and showing
  them as Never-Patched even though Ninja has them as installed.
  Migration 016 rebuilds the view with two columns:
  `ever_installed bool` (existence-only) and `last_seen_at`
  (still strictly `MAX(installed_at)`). All 53 references to
  `dps.last_seen_at` in `metabase_bootstrap.py` keep working; the
  Never-Patched / Stalled / Actively-patching classification now
  reads `ever_installed`, so the affected devices reclassify into
  Stalled with `issue_type = 'Stalled (install dates missing)'`.

### Added
- **`DASHBOARD_PATCH_CATEGORIES_EXCLUDE` env var.** Comma-separated
  list of Ninja patch categories (`patch_facts.type` values) to hide
  from every patch-context dashboard query. Default
  `DRIVER_UPDATES`. Rendered into a shared `_PATCH_TYPE_EXCLUDE` SQL
  fragment at the top of `metabase_bootstrap.py` and appended to
  every patch CTE. Empty value disables the exclusion in one place.
  Raw rows stay in `patch_facts` — exclusion is presentation-only,
  so re-enabling drivers later is a one-line config change.
- **`patch_category` column** surfaced on the
  `current_patch_state` and `latest_install_outcome` materialized
  views (sourced from `patch_facts.type`). Device Drilldown's
  Patch State History and Install History tables now include a
  `Type` column. Operator-facing tables on Patch Detail / Command
  Center / Org Overview select the column too so it's available to
  Metabase via the underlying CTE.

### Notes
- Migration 016 drop+recreates `device_troubleshooting_signal` along
  with the three patch MVs (dependency order). The signal MV's
  `patch_status`, `issue_type`, and `suggested_action` CASE blocks
  were updated to read `ever_installed` and added explicit branches
  for the dateless-stalled subset.
- `ninja_observed_at` deliberately NOT used as a fallback install
  date. It's Ninja's scan timestamp, refreshed every ingest cycle,
  so treating it as install time would falsely classify devices Ninja
  keeps re-scanning ancient installs on as actively patching.
- Commit: `TBD`

## [0.14.11] — 2026-06-04

### Changed
- **Custom-field ingest now uses Ninja's scoped values feed.** The
  ingest switched from the legacy device-centric report to
  `/queries/scoped-custom-fields`, so organization and location
  custom fields now flow through the same pipeline as device fields.
- **The `.env` allowlist now feeds the API query itself.** If
  `INGEST_CUSTOM_FIELDS_INCLUDE` is set, the ingest passes that field
  list to Ninja and only stores the selected names. Pivoted
  `v_device_custom_fields`, `v_organization_custom_fields`, and
  `v_location_custom_fields` are regenerated from the scoped feed.
- Commit: `TBD`

## [0.14.10] — 2026-06-04

### Changed
- **Org Overview and Trends now use the patching-device denominator in
  the visible KPI titles.** The second operator KPI is now
  `Fully patched % (patching devices)` everywhere it appears on the
  org-facing and trend dashboards.
- Commit: `be63e7e`

## [0.14.9] — 2026-06-04

### Changed
- **The fully-patched KPI now states its real denominator.** The
  second operator KPI is now `Fully patched % (patching devices)`,
  which matches the formula: among devices that are actively
  patching, how many have no open missing patches.
- Commit: `148de4e`

## [0.14.8] — 2026-06-04

### Fixed
- **Command Center KPI bootstrap no longer crashes at import time.**
  The new `Actively patching %` helper now carries its own device
  classification CTE instead of referencing `_PCOV_CTE` before that
  symbol is defined.
- Commit: `ba55729`

## [0.14.7] — 2026-06-04

### Changed
- **Command Center now headlines active patching instead of compliance.**
  Kept the raw count cards, but the top-right KPI now reads
  `Actively patching %` so the landing page answers whether devices
  are getting patched right now.
- **Overall Status and Org Overview now show the two operator rates.**
  The left KPI is `Actively patching %`; the right KPI is
  `Fully patched devices %`.
- **Trend cards were realigned to the same operator split.**
  Trends now show `Fully patched devices % per Day` and `Patching
  Devices per Day` instead of the old compliance/progress wording.
- Commit: `52c22e6`

## [0.14.6] — 2026-06-04

### Changed
- **Patch KPI wording split into operator-facing labels.** Command
  Center now shows a single `Devices Compliant %` headline KPI.
  Overall Status and Org Overview now split the story into `Devices
  Compliant %` on the left and `Patch Progress %` on the right.
- **Detailed patch-progress cards renamed for clarity.** The
  highest-level org breakdowns now read `Clients with Lowest Patch
  Progress`, `Patch Progress by Device Type`, `Patch Progress by
  Operating System`, and `Client Patch Progress` instead of the
  ambiguous `Patch Compliance` wording.
- **Trends dashboard gained the same KPI pair.** Added daily trend
  cards for `Devices Compliant %` and `Patch Progress %` so operators
  can see direction, not just a single static score.
- Commit: `fafe234`

## [0.14.5] — 2026-06-04

### Added
- **Device Summary now shows current reachability next to `Last Contact`.**
  Added an `Online?` column derived from the latest snapshot's
  `offline` flag, rendered as `Yes` / `No` / `Unknown`. This makes the
  difference between "recently contacted" and "currently reachable"
  explicit in the device detail view.
- Commit: `fdaca32`

## [0.14.4] — 2026-06-04

### Fixed
- **Metabase cards now get a stable hidden identity instead of being
  matched by title alone.** The bootstrap was reusing cards by display
  name, and multiple dashboards intentionally share titles like
  `Active Devices`, `Current Patch State`, `Patching Devices`, and
  `Failed Patches`. That let later dashboards overwrite earlier card
  SQL / template-tag wiring.
- Resolution: each card now carries a hidden stable UID in
  `description` and `_upsert_card()` matches on that UID. Existing
  duplicate-title cards in Metabase are left alone; new bootstraps
  create or update the correct per-dashboard card object.
- Commit: `2779967`

## [0.14.3] — 2026-06-04

### Fixed
- **Device-card filters now reach every card on Command Center,
  Overall Patching Status, Org Overview, and Trends.** Bug pattern:
  cards declared more template tags than their dashcard
  `parameter_mappings` covered, and Metabase silently broke the
  binding for the mapped parameters too. Patch Detail (which has
  tags == mappings = 8) worked fine; the other dashboards' device
  cards declared the FULL tag set but mapped only a subset
  (skipping severity).
- Resolution: every card on these four dashboards now uses the
  `_*_PARAM_MAPPINGS_FULL` variant. Device cards have a severity
  mapping declared even though their SQL never references
  `{{severity}}` — Metabase handles that fine; the mapping exists
  but does nothing.

### Notes
- Per the blueprint-first rule: `BLUEPRINT.md` written with audit
  table comparing tags vs mappings per dashboard. Hypothesis
  confirmed by the pattern: every dashboard with a mismatch had
  the symptom; Patch Detail (matched) worked.
- Device Patching Status (PCOV) tags and mappings already match
  (5/5) yet user reports the same symptom. That's a separate
  investigation in v0.14.4 if this fix doesn't resolve it.

## [0.14.2] — 2026-06-04

### Added
- **Overall Patching Status filter set expanded** to Org · Device
  Type · OS Family · Severity (all multi-select). Previously only
  Device Type. Every Overall scalar / chart / table now honors
  every applicable filter.
- **Trends filter set expanded** to Days · Org · Device Type ·
  Severity (all multi-select except Days). Time-series cards
  narrow per the active scope.
- **Org dropdown converted to multi-select** on Patch Detail,
  Org Overview, and Device Patching Status. Operator can compare
  2-3 clients at once.

### Changed
- All Overall cards have a `JOIN ninja_core.organizations o`
  added where missing. Patch-context CTEs select `severity`.
- All Trends cards JOIN organizations. Patch-counting cards
  (installs/day, failures/day, manual-age) honor severity;
  device-population cards (reboots/day, active-devices/day) don't.
- Org SQL predicates everywhere changed from `o.name = {{var}}`
  to `o.name IN ({{var}})` so the multi-select substitution
  works.
- `build_overall_parameters` and `build_trends_parameters` now
  take `org_names` (Overall also takes `os_families`).

### Notes
- Compliance scalars on Overall (overall_compliance,
  compliance_worst, compliance_all) honor Org + Device Type + OS
  Family but NOT Severity. Compliance is intended to be the fleet-
  wide coverage number; scoping by severity would change its
  meaning to "% of Critical patches installed", which is a
  different metric. Defer until operator asks.

## [0.14.1] — 2026-06-04

### Added
- **Patch Command Center filter set expanded** to Org · Device
  Type · Severity (all multi-select). Previously only Device Type.
  Every card on Command Center now honors all three filters.
- New `PARAM_CMD_ORG`, `PARAM_CMD_SEV` parameter constants;
  `_CMD_TAGS` / `_CMD_PARAM_MAPPINGS` expanded; new filter
  fragments `_CMD_FILTER_ORG`, `_CMD_FILTER_SEV_CS`,
  `_CMD_FILTER_SEV_LIR` and combined `_CMD_FILTERS_DEVICE`,
  `_CMD_FILTERS_PATCH_CS`, `_CMD_FILTERS_PATCH_LIR` mirror the
  pattern established in Org Overview.

### Changed
- All Command Center scalar SQLs that previously joined just
  `ninja_core.devices` now also join `ninja_core.organizations` so
  the Org filter can bite.
- Patch-context scalar CTEs (`cmd_approved` / `_manual` /
  `_delayed` / `_failed`) now select `severity` so it can be
  filtered in the outer WHERE.
- `cmd_clients` table applies the severity filter at CTE-level
  (inside each `WITH ...` block) so the outer LEFT JOIN
  semantics are preserved — filtering severity in the outer
  WHERE would silently drop devices with no matching patch row.

### Notes
- Audit before changes (per blueprint): every Command Center card
  was already correctly wired for the Device Type filter
  (template_tags + param_mappings + filter in SQL). User-reported
  "filters don't apply" was most likely a stale Metabase state
  from before the v0.13.6 wiring deployed. Forcing a fresh
  bootstrap should resolve it.

### Process
- Followed the new blueprint-first rule. `BLUEPRINT.md` updated
  with the proposed filter set per dashboard; user confirmed
  before implementation.

## [0.14.0] — 2026-06-04

### Removed
- **Needs Reboot scalar** demoted from the top-row Devices group on
  Patch Command Center, Overall Patching Status, and Org Overview.
  In a patch-management context Reboot is an action signal, not a
  high-level KPI — operators look at Failed / Manual / Stalled /
  Never-Patched first. The `Devices Needing Reboot` *table* on
  Overall and Org stays — that's the action queue for actually
  rebooting devices. The `Needs Reboot` column on Command Center's
  "Clients Needing Attention" table also stays. The Trends
  dashboard's "System Reboots per Day" chart is unchanged.
- Devices rows reflowed from 5 tiles (5+5+5+5+4 = 24) to 4 tiles
  (6+6+6+6 = 24) on all three dashboards.
- Removed the three reboot keys (`cmd_reboot`, `overall_reboot`,
  `org_reboot`) from `_SCALAR_ALERT_RULES`.

### Fixed
- **Filter-reach audit (Shape A + Shape B) clean.** Tags-vs-
  fragments compared on every dashboard; no parameter declared
  without a matching SQL predicate (false positives in the audit
  script were nested dict keys and timeline-window params
  consumed directly by each card's CTE).
- Removed a duplicate `[[AND d.system_name = {{device}}]]` line
  that the v0.13.9 fix had accidentally added to
  `_FILTER_PREDICATES` (the predicate was already at the bottom
  of the fragment).

### Process
- Second task to follow the new blueprint-first rule
  (`BLUEPRINT.md` written, *planning* → *in progress* → *done*).
  Audit findings recorded in the blueprint before any code
  changes.

## [0.13.9] — 2026-06-04

### Fixed
- **Patch Detail filters now apply to every card.** Two gaps
  closed:
  1. **Device filter wasn't reaching any card.** The shared
     `_FILTER_PREDICATES` fragment declared all the other
     filters but not the Device one. Adding
     `[[AND d.system_name = {{device}}]]` so picking a device
     narrows the donut / severity bar / KB chart / tables.
  2. **`detail_installs_timeline` used the old single-select
     `= {{var}}` syntax.** It inlined its predicates instead of
     using `_FILTER_PREDICATES`, so it didn't pick up the v0.13.8
     multi-select conversion. Replaced the inlined block with
     `{_FILTER_PREDICATES}` + the days predicate. Multi-select on
     Status / Device Type / Severity / Install Results / OS now
     works on the timeline too.

## [0.13.8] — 2026-06-04

### Changed
- **Multi-select dashboard filters.** Operators can now pick
  several values at once on the most-used dropdowns. New
  `_param_multiselect` helper sets `isMultiSelect: True` on top
  of the existing dropdown shape; SQL predicates updated from
  `= {{var}}` to `IN ({{var}})` so single-value and multi-value
  both work. Applied to:
    - **Patch Detail**: Current Patch State, Device Type,
      Severity, Install Results, Operating System Family.
    - **Org Overview**: Device Type, OS Family, Severity.
    - **Device Patching Status**: Device Type, Operating System
      Family, Patching Status.
    - **Patch Command Center / Overall Patching Status /
      Trends**: Device Type.
  Organization, KB Number, Device, Days remain single-select
  (each is naturally a one-value pick).

### Documentation
- New "Where to find REJECTED patches" section in `CONTEXT.md` —
  points operators at the Current Patch State pie's grey slice
  (click-through), the Patch Detail Status filter, and the
  `compliance_all` Rejected column. Confirms REJECTED is audit-
  able even though it's excluded from compliance numbers.

### Notes / honest caveats
- `isMultiSelect` JSON shape is documented in Metabase but varies
  slightly by version. First time using it in this codebase. If
  a dropdown still acts single-select after rebuild, the shape
  needs adjustment — verify the dashboard parameter JSON via the
  Metabase API.

## [0.13.7] — 2026-06-04

### Changed
- **Patch Compliance formula clarified and centralized.** REJECTED
  and DELAYED patches are now **excluded** from both numerator and
  denominator on every compliance card. REJECTED is an explicit
  opt-out from policy; DELAYED is sitting in the org's configured
  30-day auto-approval window — both are conscious decisions, not
  coverage gaps.
- New single source of truth in `metabase_bootstrap.py`:
  `COMPLIANCE_MISSING_STATES = ("APPROVED", "MANUAL", "FAILED",
  "PENDING")` + `_COMPLIANCE_CTES` reusable SQL fragment. All 6
  compliance cards (`overall_compliance`, `org_compliance`,
  `compliance_worst`, `compliance_all`, `org_device_type`,
  `org_os_family`) now use the same formula via the same CTE
  block.
- `compliance_all` table gained a "Compliance-Scope Patches" column
  showing the denominator (installed + missing) alongside the
  existing "Total Patches" (every (device, patch) we've ever seen,
  including REJECTED/DELAYED). The difference between the two
  columns is the count of REJECTED + DELAYED rows — operator can
  audit at a glance.

### Documentation
- New "Patch Compliance formula" section in `CONTEXT.md` explains
  the formula, what counts as missing vs excluded, and where the
  implementation lives.

### Process
- **New `BLUEPRINT.md` per project.** Per the new Agent Work Rule
  #5 added to `Development/DEVELOPMENT.md`, every non-trivial task
  starts with a blueprint written to `BLUEPRINT.md` at the project
  root (overwritten per task). Lets interrupted sessions resume
  cold. This commit is the first one to follow the rule.

## [0.13.6] — 2026-06-04

### Added
- **Device Type (Server / Workstation) filter on Patch Command
  Center, Overall Patching Status, and Trends.** Org Overview, Patch
  Detail, and Device Patching Status already had it. Drilldown
  skipped (per-device, irrelevant).
  Three new per-dashboard parameter declarations
  (`PARAM_CMD_CLASS`, `PARAM_OVERALL_CLASS`, `PARAM_TRENDS_CLASS`)
  + matching template tag + mapping + SQL predicate fragment
  (`_CMD_DEVICE_TYPE_FILTER`, `_OVERALL_DEVICE_TYPE_FILTER`,
  `_TRENDS_DEVICE_TYPE_FILTER`). Each card on those dashboards now
  declares `template_tags` + `param_mappings` and its SQL is wired
  via the predicate fragment. Patch counts that didn't previously
  expose `device_id` had their CTE updated and a `JOIN
  ninja_core.devices d` added in the outer SELECT.

### Notes
- Three separate filter declarations rather than one shared global
  because Metabase's parameter IDs are dashboard-scoped — the same
  `param_mapping` shape wouldn't survive sharing.
- The cards on these dashboards now have `template_tags` even when
  they previously didn't — this is the trigger that makes the
  dashboard parameter visible / wired.

## [0.13.5] — 2026-06-04

### Removed
- **Patch Command Center orphan: `cmd_patch_activity_queue`
  (Stalled Devices table).** v0.11.4 dropped the Org Overview
  twin but missed Command Center. Same redundancy — the Stalled
  Devices scalar already exposes the count, and clicking it
  drills into Device Patching Status filtered to the stalled
  bucket.

### Changed
- `cmd_approval_queue` (Manual and Delayed Patches) now spans
  full width (size_x 24) — matches the Org Overview pattern
  established in v0.11.4.

## [0.13.4] — 2026-06-04

### Fixed
- **Org Overview's `Patch Compliance by Device Type` and `…by
  Operating System` charts were blank when no org was selected**,
  and showed 0% when one was. Two bugs at once:
    1. Same compliance bug class as v0.11.1 — the SQL counted
       `WHERE cs.status = 'INSTALLED'` against a CTE filtered to
       `fact_type='patch_state'`, which never contains INSTALLED.
       Rewrote to count from `install_outcome` over the universe
       of known (device, patch) pairs.
    2. Both charts had `GROUP BY o.name, <dimension>` — producing
       one row per (org, type) combination. The bar chart needs
       one row per type. Dropped `o.name` from SELECT/GROUP BY so
       the chart renders correctly with or without an org filter.
- Same `GROUP BY o.name` issue also fixed on Org Overview's
  Current Patch State pie (`org_status`).

### Added
- **`%` suffix** on the Patch Compliance scalar via a new
  `_SCALAR_SUFFIX_RULES` table and `_apply_scalar_suffixes`
  post-processor. Mirrors the pattern of the alert-color
  post-processor. Easy to extend with more suffixes later (e.g.
  " min", " days").

## [0.13.3] — 2026-06-04

### Added
- **Scalar background coloring** on attention-required tiles. Red
  if non-zero on: Failed Patches (all 3), Never-Patched Devices
  (all 4). Amber if non-zero on: Stalled Devices (all 4), Manual
  Approval (all 3), Needs Reboot (all 3).
- Implemented as a post-process step (`_apply_scalar_alerts`) over
  the existing card lists — declares rules in a single dict keyed
  by card key, then mutates each matching card's
  `viz_settings.column_settings.column_formatting`. Single source
  of truth for which scalars are alert-colored; easy to extend.

### Notes / honest caveats
- First time this codebase ships `column_formatting` JSON via the
  Metabase API. JSON shape from Metabase docs + community
  examples; varies slightly by version. If a scalar card shows no
  color post-deploy, that's the first thing to check.
- Patch Compliance ranges (green / amber / red by threshold) not
  yet added — wanted to start with the simpler "non-zero = alert"
  pattern. Can extend the rules table to support range coloring
  next.

## [0.13.2] — 2026-06-04

### Added
- **Activities backfill CLI** (`ingest/activities/backfill.py`) —
  operator-triggered one-shot that walks `/v2/activities` backward
  from the oldest record in DB via `olderThan=<id>` pagination.
  Uses the same allowlist as the forward ingest. Stops at the
  `--days` cutoff (default 90), `--max-pages` cap (default 500), or
  Ctrl-C. Idempotent — inserts are dedup'd on the activity-id PK.
  Does NOT touch the forward-ingest cursor in `ingest_state`.
  Run with: `docker exec ninja-ingest python -m ingest.activities.backfill --days 90`
- **Dashboard JSON export tool** (`ingest/metabase_export.py`) —
  fetches each provisioned dashboard via the Metabase API and
  writes pretty-printed JSON to `metabase/dashboards/<slug>.json`.
  For version-controlled snapshots of operator-side tweaks
  (column widths, custom filter values) that don't otherwise live
  in code. Reuses the bootstrap's auth + password-resolution
  helpers. Run with:
  `docker exec ninja-ingest python -m ingest.metabase_export --user X --password-file Y`.

## [0.13.1] — 2026-06-04

### Added
- **New Ninja — Trends dashboard.** Time-series rollups derived
  from the timestamps we already capture (no schema changes). Five
  cards:
    - Patch Installs per Day (bar, last N days)
    - Failed Install Attempts per Day (bar, red)
    - System Reboots per Day (bar)
    - Active Devices Seen per Day (line, from device_snapshots)
    - Currently-MANUAL Patches by Age (bar by week
      first_observed_at — shows how stale the admin queue is)
  Single "Timeline window (days)" filter, default 90.
- **Trends added to the nav bar** between Device Status and Patch
  Detail.

## [0.13.0] — 2026-06-04

### Added
- **Patches Installed Awaiting Reboot** table on Patch Command
  Center. Joins INSTALLED patches × `needs_reboot=true` × no
  `SYSTEM_REBOOTED` activity since last install. Surfaces the
  common patching-loop gap where install landed but reboot didn't.
  Click-throughs on Organization → Org Overview, Device → Drilldown.
- **Recent Patch Activity (Fleet)** table on Patch Command Center.
  Last 100 patch-lifecycle + reboot activities across the whole
  fleet, joined to device + org. Uses the same allowlist
  (`_DRILLDOWN_ACTIVITY_CODES`) as the per-device card on Drilldown.

### Changed
- `_DRILLDOWN_ACTIVITY_CODES` and `_DRILLDOWN_ACTIVITY_CODES_SQL`
  moved to the top of the file (near the color palettes) so they
  resolve before COMMAND_CARDS at module import time.

## [0.12.7] — 2026-06-04

### Added
- **Data Freshness scalar** on Overall Patching Status (top-right,
  next to Patch Compliance). Reads `MAX(started_at)` from
  `ninja_core.run_log WHERE status='ok'` and reports either "N min
  ago" or, if > 3 hours, "STALE — last ok run N h ago". Surfaces
  ingest failures explicitly instead of silently showing stale
  numbers.

### Notes / partial
- Patch Compliance scalar size shrunk from full-width (24) to
  size 18 to make room for Data Freshness (size 6) on the same row.
- This is item 10 of the backlog. The other queued items
  (awaiting-reboot panel, fleet-wide activity feed, trends
  dashboard, scalar coloring, backfill script, JSON export) are
  still pending.

## [0.12.6] — 2026-06-04

### Changed
- **Device Drilldown activity feed cleaned up.** The "Recent
  Activity" table was showing every activity the ingest collected
  for the device, including non-patch / non-reboot rows when the
  ingest's `INGEST_ACTIVITY_TYPES_INCLUDE` was broader than the
  dashboard's purpose. Added a SQL-side allowlist
  (`_DRILLDOWN_ACTIVITY_CODES`) so the card now only shows the
  patch-lifecycle codes plus `SYSTEM_REBOOTED`.
- Card renamed: "Recent Activity" → **"Recent Patch & Reboot
  Activity"** so the operator knows what to expect.
- `PATCH_MANAGEMENT_MESSAGE` is intentionally excluded from the
  card's allowlist (noisy generic info code). Operator can edit
  `_DRILLDOWN_ACTIVITY_CODES` to tweak.

### Notes
- This is a dashboard-side filter only. The ingest is unchanged —
  if `INGEST_ACTIVITY_TYPES_INCLUDE` is permissive, the rows still
  land in `ninja_activities.activities`; the Drilldown just doesn't
  show them. Other tools / future cards can still query the full
  set.

## [0.12.5] — 2026-06-04

### Added
- **Section header dividers between scalar groups.** Virtual text
  dashcards now mark the boundaries between groups on the three
  main dashboards:
    - Patch Command Center → **Devices** / **Patches**
    - Overall Patching Status → **Compliance** / **Devices** /
      **Patches**
    - Org Overview → **Compliance** / **Devices** / **Patches**
  Each header is a markdown `### Title` rendered via a Metabase
  virtual text card (single row, full width).

### Changed
- `_set_dashboard_layout` accepts an optional `section_headers`
  list and shifts cards at/below each header's original row down by
  `SECTION_HEADER_HEIGHT` to make room. Card specs keep their
  natural row numbers (0, 4, 8…); the layout helper computes the
  offset.
- `build_dashboards` now declares `section_headers` per dashboard
  alongside `cards` / `parameters`.

### Notes
- Drilldown, Patch Detail, and Device Patching Status didn't
  receive headers — they don't have the device/patch/compliance
  scalar grouping pattern.
- If Metabase's virtual text dashcard rejects this exact JSON
  shape, the dashboard PUT will 4xx — should fall back cleanly
  since pass 1a still creates the dashboards (just without the
  layout) and pass 2 click_behaviors don't touch dashcards.

## [0.12.4] — 2026-06-04

### Added
- **Pie / bar color coding (green / amber / red).** Two shared
  palettes baked into the bootstrap:
    - `PATCH_STATE_COLORS` — by patch_facts.status value. INSTALLED
      green, APPROVED/DELAYED blue, MANUAL amber, FAILED red,
      REJECTED grey.
    - `PATCH_ACTIVITY_COLORS` — by device patching state. Patching
      Devices green, Stalled Devices amber, Never-Patched Devices
      red.
  Applied to: Current Patch State pies on Overall Status, Patch
  Detail, Device Drilldown, and Org Overview; Patching Status pie
  + Operating-System stacked bar on Device Patching Status.

### Notes
- Section header markdown dividers between scalar groups still
  deferred — needs a layout-shift refactor to insert virtual
  cards between existing rows.
- Scalar background coloring also deferred — Metabase
  column_formatting JSON shape varies by version and would need
  live verification first.

## [0.12.3] — 2026-06-04

### Added
- **Needs Reboot** scalar on Overall Patching Status (Fleet) — was
  only on Command Center; now both dashboards expose it as the
  fifth tile in the Devices row.
- **Patching Devices** and **Needs Reboot** scalars on Org Overview
  — Org now has the full canonical Devices row: Active · Patching ·
  Stalled · Never-Patched · Needs Reboot.
- **Severity filter wiring** on the remaining 5 Org Overview patch
  scalars (Failed Patches, Approved Patches, Manual Approval,
  Delayed Patches, Current Patch State pie). Each CTE now selects
  `severity`, and `_ORG_FILTERS_PATCH_CS` / `_ORG_FILTERS_PATCH_LIR`
  applies the predicate. Every Org dashboard filter now narrows
  every applicable card.

### Changed
- Overall Patching Status and Org Overview row-4 layouts reflowed
  from 3–4 scalars at size 6/8 to **5 scalars at sizes 5+5+5+5+4**
  to match Command Center.

## [0.12.2] — 2026-06-04

### Changed
- **Device Drilldown's `Patch History` table split into two tables.**
  The old single table commingled `fact_type='patch_state'` rows
  (current state of pending patches) and `fact_type='install_outcome'`
  rows (install attempts). One column called "Current Patch State"
  meant different things on different rows. Now:
    - **Patch State History** (`device_patch_state_history`) — only
      `fact_type='patch_state'` rows. Columns: Device · KB · Patch ·
      Patch State · Severity · First Seen in This State · Last Seen.
    - **Install History** (`device_install_history`) — only
      `fact_type='install_outcome'` rows. Columns: Device · KB ·
      Patch · Install Outcome · Severity · Install Attempt Time ·
      Last Seen.
- **Org Overview cards now honor the dashboard filters.** Every Org
  card's SQL was updated to apply Organization + Device Type + OS
  Family filter predicates via the `_ORG_FILTERS_DEVICE` helper. The
  two patch-context tables (`org_failed_queue`, `org_action_queue`)
  additionally honor the Severity filter via `_ORG_FILTERS_PATCH_LIR`
  / `_ORG_FILTERS_PATCH_CS` helpers.

### Notes / deferred
- Severity filter only wired to the two patch-context tables.
  Adding it to other patch cards requires CTE rewrites to expose
  severity to the FROM/WHERE clauses; deferred.
- Section header markdown cards between scalar groups: still not
  added — visual row-grouping is in place, explicit headers are
  not.
- Color coding (green/amber/red): still deferred.
- Patching Devices scalar on Org Overview and Needs Reboot scalar
  on Overall Status / Org Overview: still not added.

## [0.12.1] — 2026-06-03

### Changed
- **Consistent card grouping across Command Center, Overall Patching
  Status, and Org Overview.** Each of the three dashboards now uses
  the same row structure for top-of-page scalars:
    - *Devices* row: Active · Patching · Stalled · Never-Patched
      (Command Center also includes Needs Reboot here — see notes).
    - *Patches* row: Approved · Manual · Delayed · Failed.
  Cards reordered in code to match this canonical order; charts and
  tables shifted to higher row numbers to make room.
- **Overall Patching Status now has a full-width Patch Compliance
  headline scalar** at row 0. Compliance is neither a device nor a
  patch metric — it's a top-level KPI and lives at the top of the
  page now.
- **Org Overview Patch Compliance scalar** moved from row 0 col 6 (a
  small tile next to Active Devices) to row 0 col 0 size 24
  (full-width headline) — same prominence as Overall Patching Status.

### Added
- **Org Overview dashboard filters:** Device Type, OS Family, and
  Severity dropdowns alongside the existing Organization filter.
  Filter helpers (`_ORG_FILTERS_DEVICE`, `_ORG_FILTERS_PATCH_CS`,
  etc.) defined for use across the Org cards.

### Notes / deferred
- **Per-card SQL wiring to the new Org filters is not yet
  applied** — the dropdowns are defined and visible but every Org
  card still queries the full org dataset. Wiring each card's SQL
  to use `[[AND ...]]` predicates is queued for v0.12.2.
- **Section header markdown cards** ("Devices" / "Patches" /
  "Compliance" subheadings between groups) are deferred — the
  visual grouping by row is in place, but explicit headers are
  not yet added.
- **Color coding** (green/amber/red) deferred to v0.12.2.

## [0.12.0] — 2026-06-03

### Changed
- **Dashboard renames** to disambiguate the two "status" views:
    - "Ninja — Overview" → **"Ninja — Overall Patching Status"**
      (fleet-wide rollup of compliance + state breakdowns)
    - "Ninja — Patching Status" → **"Ninja — Device Patching Status"**
      (per-device classification: Patching / Stalled / Never-Patched)
  Bootstrap renames each in place if the legacy name is found, so
  existing dashboard IDs (and Metabase favorites / shared links)
  survive.
- Nav bar labels condensed to **"Overall Status"** and **"Device
  Status"** to fit the strip.
- **Device Patching Status row 0** reordered so **Active Devices**
  is leftmost, consistent with every other dashboard. Order is now
  Active · Patching · Stalled · Never-Patched.

### Added
- **Patch Command Center is now the Metabase default homepage.**
  Bootstrap PUTs `custom-homepage=true` +
  `custom-homepage-dashboard=<command_center_id>` so operators
  land there instead of the generic Metabase home. Best-effort —
  on API rejection (older Metabase versions), the bootstrap logs a
  warning and continues; operator can set it manually via Admin →
  Settings → General → Custom Homepage.

## [0.11.4] — 2026-06-03

### Fixed
- **Full click-thru audit.** Applied the v0.10.2/v0.11.3 lesson
  (lowercase snake_case SQL aliases for click-source columns) to
  every remaining table that still used the capitalized quoted
  pattern: `cmd_failed_queue`, `cmd_approval_queue`,
  `cmd_patch_activity_queue`, `detail_all_devices`, `detail_all_kbs`,
  `detail_table`, `device_patch_history`, `pcov_by_org`,
  `pcov_all_devices`, `org_failed_queue`, `org_action_queue`. Every
  click-source column is now an unquoted snake_case alias with its
  `column_click_behavior` key matching exactly.

### Changed
- **Org Overview reflowed.** Removed the `Stalled Devices` table
  (`org_patch_activity`) that lived as a half-width card next to
  `Manual and Delayed Patches`. The stale/never-patched populations
  are already exposed by the org_stale / org_never scalars and the
  Devices Needing Reboot table — the orphan table was redundant.
- `Manual and Delayed Patches` table (`org_action_queue`) now spans
  full width (size_x 24).

## [0.11.3] — 2026-06-03

### Fixed
- **`Devices Needing Reboot` click misalignment** (Fleet + Org).
  After v0.11.2 enabled per-column click_behavior at the dashcard
  level, the device + device_type columns drilled correctly but
  organization clicks did nothing and last_contact wrongly
  navigated to Org Overview. Two corrections:
    1. Removed the `target: "self", preset: {}` inert placeholders
       on info columns (last_contact, reported_at, "Last Contact").
       They were the v0.7.4 "suppress the default drill popup"
       experiment and were misaligning real click_behaviors to the
       wrong columns. Trade-off: info columns now show the default
       Metabase drill popup; the meaningful drills work cleanly.
    2. Gave every column an explicit lowercase `AS` alias and
       converted `org_reboot_devices` (Org Overview) from
       capitalized-quoted aliases to the same lowercase pattern
       Fleet's `needs_reboot` now uses.

## [0.11.2] — 2026-06-03

### Fixed
- **Per-column table click-thrus still showed Metabase's default
  "filter by this value" popup** after v0.11.1, even though
  whole-card click_behavior (e.g., bar charts) was working fine on
  the same dashboards. Root cause: Metabase silently ignores
  per-column `click_behavior` set in the **card**'s
  visualization_settings; it only honors it when set on the
  **dashcard**'s visualization_settings. The bootstrap was writing
  both whole-card and per-column behaviors to the card; the latter
  had no effect. Fix: per-column click behaviors are now written
  during dashboard layout (pass 1b) into each dashcard's own
  `visualization_settings.column_settings`. Whole-card
  `click_behavior` stays at the card level (it works there). Affects
  Command Center "Clients Needing Attention", Fleet Overview
  "Client Patch Compliance" / "Devices Needing Reboot", Org
  Overview tables, Patch Detail / Drilldown / Patching Status tables.

## [0.11.1] — 2026-06-03

### Fixed
- **Patch Compliance always 0.** Fleet Overview's `Clients with
  Lowest Patch Compliance` chart, `Client Patch Compliance` table,
  and Org Overview's `Patch Compliance` scalar all reported 0 % for
  every client. The compliance numerator counted
  `WHERE status='INSTALLED'` against a CTE filtered to
  `fact_type='patch_state'`, but per the v0.9.0 split, INSTALLED
  rows live in `fact_type='install_outcome'`. The patch_state side
  never contained any installs, so the numerator was always 0.
  Compliance now computes installed = distinct (device, patch) with
  any install_outcome=INSTALLED row over the universe of all
  (device, patch) pairs we know about.
- **Fleet Overview table click-thrus didn't navigate.** Per the
  v0.10.2 lesson, Metabase per-column click_behavior is more
  reliable referencing stable lowercase snake_case SQL aliases than
  quoted display strings (`"Organization"`, `"Device"`, etc.).
  `Client Patch Compliance` and `Devices Needing Reboot` both used
  the quoted-display pattern; they now use `organization`,
  `device`, `device_type` aliases with click keys to match.

### Added
- **Patching Devices** scalar on Patch Command Center — completes
  the device-state triple (Patching / Stalled / Never-Patched) that
  was already on Fleet Overview but missing here. Row 4 reflowed to
  5 scalars at widths 5+5+5+5+4.

## [0.11.0] — 2026-06-03

### Added
- **Cross-dashboard nav bar.** Every dashboard now opens with a
  one-row markdown panel linking to the other dashboards in the set
  (Command Center · Fleet Overview · Org Overview · Patching Status ·
  Patch Detail · Device Drilldown). The current dashboard is bolded
  without a link. Implemented via Metabase virtual text dashcards
  (`card_id: null` + `visualization_settings.virtual_card`).
- Fleet Overview now splits the lumped **Manual / Delayed** scalar
  into **Manual Approval** and **Delayed Patches** (consistent with
  Command Center and Org Overview). Row 0 reflowed to 5 scalars
  (Active Devices · Approved Patches · Manual Approval · Delayed
  Patches · Failed Patches).

### Changed
- Terminology pass for consistency across all 6 dashboards:
  - **Patching Status** (overloaded as both a dashboard name and a
    card title for the patch_facts.status pie) → the pie card title
    is now **Current Patch State** everywhere. The PCOV dashboard
    keeps "Patching Status" as the dashboard concept.
  - **Patch Activity** (PCOV dashboard column + filter + card
    titles) → **Patching Status**. Card titles are now "Patching
    Status by Device Type / OS / Organization".
  - Device-state triple uses unambiguous device-focused labels:
    **Patching Devices / Stalled Devices / Never-Patched Devices**
    (previously "Recent Patch Activity / Stale Patching / Never
    Patched" — which read as patch states, not device states).
  - **Delayed Install** → **Delayed Patches** (parallels Approved /
    Failed / Manual).
  - **Approved Windows Devices** (Patching Status total) → **Active
    Devices** (consistent with Fleet and Org).
  - SQL aliases, viz dimension references, dropdown values, and
    click-behavior column keys all renamed in lockstep so dashboards
    keep working.
- `_set_dashboard_layout` now accepts an optional `nav_markdown` and
  shifts every card down by `NAV_HEIGHT` rows when present. Card
  specs keep their natural row numbers (0, 4, 8…) — the helper
  inserts the offset.
- `run_bootstrap` restructured into three passes: cards+dashboards
  first, then layouts (with nav bar) once all dashboard IDs are
  known, then click behaviors.

## [0.10.2] — 2026-06-03

### Fixed
- Fixed the **Clients Needing Attention** organization click on
  **Ninja — Patch Command Center** by restoring a stable lowercase
  `organization` SQL alias for Metabase's table-column click behavior.
- Clarified mixed-unit table columns so patch counts say `Patches`
  and device counts say `Devices`.

## [0.10.1] — 2026-06-03

### Fixed
- Changed the default stale-patching threshold from 7 days to 35 days
  to match real MSP patch cadence, where devices may patch weekly or
  monthly.
- Centralized the non-filter dashboard stale threshold as
  `DEFAULT_STALE_PATCH_DAYS` so Command Center, Overview, and Org
  Overview do not drift from each other.
- Kept **Ninja — Patching Status** configurable via the dashboard
  `Stale threshold (days)` filter, now defaulting to 35.

## [0.10.0] — 2026-06-03

### Added
- New **Ninja — Patch Command Center** dashboard as the operator
  landing page. It surfaces fleet-wide action queues for clients
  needing attention, failed patches, manual/delayed patches, stale
  patching, never-patched devices, and reboot work.
- Operating-system dashboard filters now use stable OS families:
  `Windows 11`, `Windows 10`, `Windows Server`, `Other Windows`, and
  `Unknown`.

### Changed
- Rebuilt **Ninja — Org Overview** as an actionable client patching
  view instead of a mostly decorative summary page. It now has
  org-scoped KPIs plus queues for failed patches, manual/delayed
  patches, stale/never-patched devices, and reboot attention.
- Dashboard labels and visible table columns now use operator-facing
  terminology: `Active Devices`, `Approved Patches`, `Manual
  Approval`, `Delayed Install`, `Failed Patches`, `Recent Patch
  Activity`, `Stale Patching`, `Never Patched`, `Device Type`,
  `Operating System`, `Patching Status`, and `Install Results`.
- Device Type filters now use readable values (`Windows Workstation`,
  `Windows Server`) instead of raw Ninja node-class codes.
- Query-string drill links now URL-encode preset filter values so
  dashboard links work with labels containing spaces.

## [0.9.0] — 2026-06-03

### Added
- `ninja_patches.patch_facts.fact_type` now explicitly marks rows as
  `patch_state` (`/queries/os-patches`) or `install_outcome`
  (`/queries/os-patch-installs`). Migration
  `006_patch_fact_type.sql` backfills existing rows by status.

### Changed
- Patching Status stale/active classification now uses the latest
  available install/attempt timestamp (`MAX(installed_at)`) from
  `install_outcome` rows. The `Stale threshold (days)` dashboard
  filter continues to control the active/stale split.
- Dashboard SQL that needs install outcomes now filters by
  `fact_type = 'install_outcome'` instead of inferring source from
  status values.

## [0.8.1] — 2026-06-03

### Fixed
- Split dashboard patch semantics into **current patch state** and
  **latest install outcome**. A patch can currently be `APPROVED`
  while its most recent install attempt is `FAILED`; the old
  current-state-only queries hid those failed installs.
- Fleet and Org **Failed Installs** cards now count the latest
  `FAILED` install outcome per `(device_id, patch_uid)`.
- Patch Detail now has an **Install Outcome** filter separate from
  the current-state **Status** filter, and the detail table shows both
  `current_status` and `last_install_outcome`.
- Org Top Problem Patches now prioritizes latest failed install
  outcomes while still showing current queued states.

## [0.8.0] — 2026-06-03

### Added
- New **Ninja — Org Overview** dashboard. Fleet org clicks now drill
  into this org-scoped overview instead of jumping straight to the
  flat Patch Detail list.
- Patch Detail now has a real **Device** dropdown filter populated
  from active Windows devices.

### Changed
- Renamed **Ninja — Patch Coverage** to **Ninja — Patching Status**.
  Bootstrap renames the old dashboard in place when found.
- Device Drilldown now uses an exact Device dropdown instead of a
  free-text substring filter.
- Dashboard scope is now Windows patching only:
  `WINDOWS_WORKSTATION` and `WINDOWS_SERVER`.

### Database
- Migration `005_active_windows_devices_view.sql` replaces
  `ninja_core.v_active_devices` on already-deployed stacks so the
  Windows-only scope applies even if migration `004` already ran.

## [0.7.4] — 2026-06-03

### Changed
- **Consistent table click behavior.** Previously, table cells with a
  configured drill (colored link) navigated as expected, but cells in
  unconfigured columns showed Metabase's default "filter by this
  value" drill-through prompt — which is meaningless on tables that
  have no logical filter destination. Each table now declares every
  column's behavior explicitly: meaningful columns navigate; purely
  informational columns (timestamps, durations, status text on
  diagnostic tables) get a self-link with empty preset to suppress
  the prompt.
    - `needs_reboot`: `last_contact`, `reported_at` → inert.
    - `ingest_health`: all 7 columns → inert (it's diagnostic; no
      drill destination makes sense).
- `_build_click_behavior_json` now accepts `current_dash_id` and
  resolves `target: "self"` in the preset path to a URL pointing at
  the current dashboard (empty preset = no-op self-link).

## [0.7.3] — 2026-06-03

### Added
- **Number cards drill into target dashboards on click.** Previously
  clicking a scalar tried to "filter for this value" (meaningless on
  a one-cell display). Now each scalar pre-sets a filter on the
  target dashboard via a URL link:
    Overview "Patches Ready" → Detail filtered to APPROVED
    Overview "Failed" → Detail filtered to FAILED
    Overview "Manual / Delayed" → Detail filtered to MANUAL
    Overview "Active Devices" → Detail (no filter — see all)
    Overview "Patching Active (7d)" → Patch Coverage filtered to active_patching
    Overview "Patching Stale" → Patch Coverage filtered to stale_patch_data
    Overview "No Patch Data" → Patch Coverage filtered to no_patch_data
    Patch Coverage scalars → same dashboard with `pcov_status` pre-set

### Fixed
- Five stray `ORDER BY n DESC` references that should have been
  `ORDER BY patches DESC` — leftover from the earlier `AS n` →
  `AS patches` rename. Caused "column 'n' does not exist" on Patch
  State Breakdown and the four Detail charts.
- `COUNT(*) AS needs_attention` had been corrupted to
  `COUNT(*) AS patcheseeds_attention` by the same blunt replace —
  fixed back. Operator never saw this fail because the card with
  the corrupted column returned NULL (which Metabase rendered as
  "no value").

## [0.7.2] — 2026-06-03

### Fixed
- **Metabase bootstrap was crashing silently** with
  `NameError: name 'DASH_DETAIL' is not defined` at module import.
  The four dashboard-name constants (DASH_OVERVIEW / DASH_DETAIL /
  DASH_DRILLDOWN / DASH_PCOV) were defined ~300 lines below the
  card specs that referenced them — Python tries to resolve those
  names at module-load time, fails. Constants moved to the top of
  the file, before any card definitions.
- **Impact:** since v0.5.0 the auto-bootstrap has been throwing
  this NameError on every container start (logged but not raised
  by `bootstrap_metabase`'s try/except). All dashboard changes
  shipped between v0.5.0 and v0.7.2 — patch coverage tunings, OS
  bar fix, active-devices view, click behaviors, workstation
  default — haven't actually been applied to your Metabase.
  This commit unblocks all of those at once.

## [0.7.1] — 2026-06-03

### Fixed
- Activities ingest now filters server-side by `statusCode=<code>`
  (one call per allowlist entry) instead of `type=<source>` with
  client-side filtering. This:
    - Catches SYSTEM_REBOOTED reliably regardless of which Ninja
      `type` bucket it lives in. (`type=SYSTEM` we'd been using
      returns Ninja platform audit events — admin logins, node
      access grants — NOT device reboots.)
    - Reduces API surface: 10 small targeted calls instead of pulling
      whole MONITOR / PATCH_MANAGEMENT / SYSTEM buckets and dropping
      most records.
    - No more risk of silently missing relevant events because they
      happen to be filed under a different bucket.
- Empty `INGEST_ACTIVITY_TYPES_INCLUDE` falls back to old
  `type=<source>` behavior (backward compat) with a WARN log
  encouraging operator to set the allowlist.

## [0.7.0] — 2026-06-03

### Performance

Patch ingest stops re-walking the entire 376k install history every
hour. The two patch endpoints now use different strategies:

  - `/queries/os-patch-installs` (events: INSTALLED, FAILED) →
    INCREMENTAL via `?installedAfter=<unix_seconds>`. High-water
    mark = MAX(installed_at) currently in patch_facts. First run
    pulls everything; subsequent runs pull only patches installed
    since the last seen install.
  - `/queries/os-patches` (state: PENDING, APPROVED, REJECTED,
    DELAYED, MANUAL) → FULL PULL each run. State transitions don't
    always carry a usable timestamp, and the set is small (~50k).

Impact: a normal hourly tick that previously HTTP'd 376k records
now HTTP's only the handful installed in the last hour, plus the
~50k state records. Estimate: minutes → seconds per cycle.

SCD-2 hash dedup means re-fetching boundary records (anything
installed at the same second as our high-water mark) is harmless.

## [0.6.1] — 2026-06-03

### Removed
- `triggered_by_user_id` column from the Device Drilldown's "Recent
  Activities" card. Ninja's `userId` is internal audit (which API
  client/service triggered the event), not the device's logged-in
  user or an MSP technician — no business value. Schema keeps the
  column to avoid a destructive migration but it's no longer
  surfaced anywhere. Documented as permanently-parked in TODO.md.

## [0.6.0] — 2026-06-03

### Added
- **Activities ingest is now working** end-to-end against the live
  Ninja instance. Findings from `probe_activities.py`:
    - Server-side filter param is `type=<source>` (NOT `activityType`
      — that one is silently ignored).
    - Pagination back: `olderThan=<id>` walks to older records.
    - Pagination forward: `after`/`newer`/`newerThan`/`from` all work
      equivalently (we use the high-water mark approach: walk back
      with `olderThan` from latest, stop when we cross our cursor).
  Per source (PATCH_MANAGEMENT, SYSTEM, etc.), iterate older pages
  until cross last_id, filter by statusCode allowlist, insert with
  ON CONFLICT DO NOTHING (id is PK).
- Activity records are joined to `ninja_core.devices` via
  `deviceId`. If Ninja reports activity for a device we don't ingest
  (PENDING / DECOMMISSIONED), `device_id` is NULL'd (activity still
  recorded, just without device link).
- **Device Drilldown** gains a "Recent Activities" table showing
  the last 200 activities for the searched device — event code,
  human label, message, the **userId who triggered it**, and the
  activity category. That's the "by whom" surface for events that
  carry it (login, software install, etc.).

### Field mapping (Ninja API → our schema)
  `id`           → `id`
  `activityTime` → `activity_time`
  `deviceId`     → `device_id` (NULL if device not in our table)
  `userId`       → `user_id` (the user who TRIGGERED the activity)
  `activityType` → `source_name` (broad bucket: MONITOR, PATCH_MANAGEMENT...)
  `type`         → `source_type` (friendly name)
  `statusCode`   → `activity_type` (specific event code)
  `status`       → `subject` (human label)
  `message`      → `message`

### Process
- VERSION 0.6.0. Activities is a new functional capability (not just
  a bugfix); first time we're surfacing Ninja's event log.

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
