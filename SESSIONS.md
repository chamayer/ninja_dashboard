# Sessions

Chronological dev journal. What was done each session, why decisions
were made, what's pending. Useful for resuming interrupted work.

---

## 2026-06-11 — v0.19.0 Devices redesign + drilldown + NO AV fix

**Why:** v0.18.0 shipped the filters but operator review surfaced
several issues:

- The Devices top filters only made sense for some cards (the gap
  cards) and not others (Need action, Stale by customer, Ignored)
  with no visual cue about which card responded to which filter.
- `s1_exempt` was always false — every device showed `NO AV = No`.
  The Ninja collector probed raw_data keys that don't exist on the
  `/v2/devices-detailed` response.
- `Need action` excluded degraded-compliant rows, which made the
  `State = Degraded` filter a silent no-op and hid a real operator
  signal (agent installed everywhere, one platform stopped checking
  in).
- No per-device drilldown — operator could see the noncompliant row
  but couldn't see history (when did it first fail, when was it
  alerted on, who ignored it before).
- `Required coverage` could set the platform combo but not the
  staleness window — and the existing combo write reset
  `max_age_days` to 30 as a side effect.

**Done:**
- Sectioned the Devices layout into Triage / Gap analysis /
  Maintenance with reusable section-header infrastructure that other
  dashboards can opt into.
- Applied Customer filter uniformly across every Devices card.
- Broadened Need action to include degraded-compliant rows and
  inlined the suppression check so the Degraded state filter now
  matches.
- Fixed `s1_exempt` detection by joining to `ninja_core.policies`
  for both the assigned and role policies and checking the policy
  NAME for `NO AV` (case-insensitive). Tags-array check preserved.
- Renamed the `AV` / `AV exempt` column and filter to `NO AV` so it
  matches the Ninja tag/policy convention operators recognize.
- Added per-customer max age preset buttons (7d / 30d / 90d) on the
  Required coverage card. New endpoint
  `/agent-compliance/action/set-max-age` (`/a/sd`) writes through
  without touching the platform combo.
- Built the per-device drilldown dashboard (off the top nav by
  design — only reachable via row click on a Device column). Surfaces
  per-run state from `compliance_matrix_history`, findings history,
  alert deliveries joined to `notification_routes`, and ignore
  history.
- Demoted the cross-customer conflict view from Customers to Debug
  per operator feedback that it's a data-quality signal, not a daily
  concern.
- Surfaced the new-customer-candidates count as a table on Today so
  the discovery signal is visible on the landing page, not only
  inside Customers.

**Commits:** `13c710a` (NO AV fix), `806d15e` (max age UI),
`0088967` (Devices layout + Degraded), `aa08bf1` (demote
cross-customer), `16d8e18` (drilldown), `d0bec89` (Today new-customer
table).

**Validation:**
- `python -m compileall ingest` passes (all touched files).
- Live host run pending: redeploy ingest, trigger
  `/run/agent-compliance` to flip `s1_exempt` on policy-exempt
  devices, `POST /bootstrap-metabase`, verify the section headers
  render, drilldown click-through resolves with customer + host
  URL params, and the AV exempt filter shows the right rows on
  Yes / No.

**Pending follow-ups (see TODO):**
- First end-to-end alert delivery.
- DJ-UTAH-class alias gap diff vs PowerShell `$OrgConfig`.
- Drilldown nice-to-haves listed under Backlog.
- Source enable/disable from the UI (currently psql only).

## 2026-06-11 — v0.18.0 Agent Compliance operator-actionable Devices

**Why:** Two parallel pushes landed on the same day. First, codex
spent the day rebuilding the operator surface against the
`AGENT_COMPLIANCE_OPERATOR_UI.md` and `AGENT_COMPLIANCE_ALERT_WORKFLOW.md`
contracts (separate Today / Devices / Customers / Health / Debug
dashboards, humanized labels, per-row action links, customer mapping +
coverage workflow). Second, the day ended with a real operator
complaint: the gap-summary cards on Devices were counts only, with no
way to drill into the rows behind them, and there was nowhere to clear
stale-device noise in bulk for one customer.

**Done — codex (committed earlier in the day):**
- Rebuilt the dashboard surface around the operator-UI contract
  (`3b9d2b1`).
- Closed the review-queues and source-health work into their own
  surfaces so primary Devices stays device-level (`37e152b`).
- Customer mapping workflow + coverage controls + active platform gap
  filters (`16d89d8`, `809c72b`, `8a9cfda`).
- Hardened action-link URL handling: short paths, browser-safe action
  base URL, ingest port published to host, redacted logs (`6360b70`,
  `2d4e3ad`, `29f8318`, `bb27daf`, `aab87a2`, `e99d439`).
- Dropped placeholder org names and demoted bad seed orgs so the
  customer-review queue stops surfacing noise (`4b46ffe`, `51bb3b4`).

**Done — this session (picking up where codex left off):**
- Fixed `/a/*` short-path 404. `do_GET` only routed
  `/agent-compliance/action/` paths to the handler, so every short
  alias generated by Metabase action cells was 404'ing (`2615a57`).
- Wired the previously uncommitted `bulk_ignore_devices()` to a new
  `/agent-compliance/action/bulk-ignore-stale` endpoint (`/a/bs` short
  alias) and added a `Stale devices by customer` card with a
  `Bulk ignore` CTA. Bulk path is intentionally narrow: stale only,
  one customer per click (`d26e9eb`).
- Added targeted filters + drill-through on Devices: dashboard-level
  Customer / Missing / Online in / State parameters, mapped per-card
  to the relevant subset. Row click on `Missing but online elsewhere`
  reopens the dashboard with that combo pre-applied — the count card
  is now actionable (`8f0d663`).

**Filter design rationale (not bulk-applied):**
- One scenario-exploration surface, not filters on everything. The
  workhorse is `Active platform gap details`; the summary cards
  drill into it via URL params on the same dashboard.
- `Need action` gets Customer + State because per-customer triage and
  "show me stale only" are the most common asks.
- Charts, ignore lists, and the new stale-by-customer card stay
  unfiltered — they're summaries.

**Validation:**
- `python -m compileall ingest` passes (main, metabase_bootstrap,
  config_loader).
- Live host run pending: apply migrations, `POST /bootstrap-metabase`,
  verify the filter widgets render, drill-through resolves, and the
  bulk-ignore CTA returns 200.

**Pending (for the next session):**
- Gap assessment: original PowerShell report vs current build vs
  stated intent in the operator-UI / alert-workflow docs.
- First end-to-end alert: configure a notification route, trigger an
  alert run, verify delivery.

## 2026-06-10 — v0.17.3 org excludes and alias-aware discovery

**Why:** Claude left a concrete next-commit bundle from the PowerShell
parity notes: move org excludes into the DB, make discovery alias-aware
so typo variants do not create duplicate canonical orgs, and filter
excluded orgs out of the unresolved-observations operator card.

**Done:**
- Added migration `021_org_excludes.sql`.
- Replaced the hardcoded org-exclude constant with a DB-backed lookup.
- Taught discovery to prefer existing client names/aliases before
  creating a new canonical org.
- Filtered the unresolved-observations Metabase card by `org_excludes`.

**Validation:**
- `python -m compileall ingest` passes.
- `git diff --check` passes.

## 2026-06-10 — v0.17.1 alignment persistence fix

**Why:** The v0.17.0 parity schema still had one stale-lookup bug:
newly discovered canonical orgs were inserted, but the alignment rows
were being assembled from the pre-insert client lookup. That left the
alignment tables empty in live validation.

**Done:**
- Rebuilt alignment aliases and alignment rows after the refreshed
  client lookup.
- Ensured newly discovered canonical orgs are persisted into
  `org_alignment_current` and `client_aliases`.

**Validation:**
- `python -m compileall ingest` passes.

## 2026-06-10 — v0.17.0 Agent Compliance PowerShell parity schema

**Why:** The prior fixes improved behavior, but full parity with the
PowerShell report requires persisted alignment status and matrix fields,
not hidden in alias resolution. The operator needs to prove mapping and
collection against the original script.

**Done:**
- Added migration `020_agent_compliance_parity.sql`.
- Added current/history org alignment tables and views.
- Persisted PowerShell-style alignment fields:
  `MATCHED`, `FUZZY`, `MISSING`, `NA`, `CONFIGURED`,
  `OverallStatus`, platform names, merged-from, suggested config.
- Added PowerShell report fields to current/history matrix:
  per-platform presence/online/last-seen/device-id, S1 exemption, and
  degraded state.
- Updated matrix stale/degraded semantics to match PowerShell.
- Added Metabase cards for alignment mismatches and degraded devices.
- Added `AGENT_COMPLIANCE_V2_BLUEPRINT.md`.

**Validation:**
- `python -m compileall ingest` passes.
- `git diff --check` passes.
- Pending host migration/run validation.

## 2026-06-10 — v0.16.4 PowerShell alignment parity correction

**Why:** The previous dynamic mapping pass admitted every observed
platform group as a client. That was not full PowerShell parity. The
PowerShell script builds a canonical alignment map first, collapses
normalized-identical names, prefers configured names/Ninja names, then
uses fuzzy Ninja absorption only when unambiguous and complementary.

**Done:**
- Replaced synthetic default aliases with persisted alignment aliases.
- Canonical selection now follows configured client, Ninja, S1, LMI.
- Normalized-identical platform names route to one canonical client.
- Added fuzzy non-Ninja to Ninja absorption with the original ambiguity
  guardrail.
- Alias lookup now applies deterministic source precedence.

**Validation:**
- Pending deployment and live `/run/agent-compliance` validation.

## 2026-06-10 — v0.16.3 PowerShell org-alignment parity

**Why:** Live validation showed many resolved platform group names still
unresolved as clients. The original PowerShell does not limit the
matrix to static `OrgConfig` entries; it builds an alignment map from
all observed Ninja orgs, SentinelOne sites, and LogMeIn groups, then
applies explicit config only as overrides.

**Done:**
- Added dynamic client discovery from observed platform group names.
- Added default Ninja org, SentinelOne site, and LogMeIn group aliases
  for every enabled client by client name.
- Preserved explicit configured aliases as additive mappings.
- Preserved original excludes: `Abe Private`, `AMRose-Test`.
- Refactored agent-compliance runs to fetch all sources first, sync
  observed clients, reload config, then resolve/insert observations.

**Validation:**
- Pending deployment and live `/run/agent-compliance` validation.

## 2026-06-10 — v0.16.2 LogMeIn PowerShell parity correction

**Why:** Live host validation showed LogMeIn host rows had `groupid`,
but `platform_group_name` was blank. The original PowerShell already
worked this out by using `$resp.groups`, `$g.id`, `$g.name`, and
`$h.groupid`. The migration gap was Python's case-sensitive JSON dict
access versus PowerShell's case-insensitive property access.

**Done:**
- Updated the LogMeIn collector to use case-insensitive JSON lookup for
  PowerShell-equivalent properties.
- Kept the original PowerShell semantics: build a group map from
  `groups` using group `id`/`name`, then resolve each host by `groupid`.
- Added LogMeIn parser markers into raw observation data:
  `lmi_group_id`, `lmi_group_name_resolved`, and `lmi_group_map_size`.

**Validation:**
- Pending deployment and live `/run/agent-compliance` validation.

## 2026-06-10 — v0.16.1 Agent Compliance mapping parity pass

**Why:** Re-review of the original PowerShell script showed that
mapping behavior is core to trustworthy counts. The v0.16.0 foundation
collected data, but did not fully preserve LogMeIn group resolution,
LogMeIn rate-limit handling, normalized alias matching, hostname prefix
fallback, or Ninja `NO AV` SentinelOne exemption behavior.

**Done:**
- Fixed LogMeIn `/v2/hostswithgroups` parsing to map `payload.groups`
  by ID and resolve host group names from `groupid`/`groupId`.
- Added one retry after a 61-second minimum wait for LogMeIn HTTP `429`.
- Added normalized alias lookup for org/site/group aliases.
- Extended hostname normalization to strip curly apostrophes.
- Added conservative unique-prefix hostname matching for truncated names.
- Added Ninja raw-data marker for `NO AV` tag/policy evidence and
  excluded SentinelOne from required platforms for those devices.
- Added `AGENT_COMPLIANCE_MIGRATION_REVIEW.md`.

**Validation:**
- `python -m compileall ingest` passes.

**Pending:**
- Deploy to host, trigger `/run/agent-compliance`, and compare
  unresolved observations, missing-platform counts, and `NO AV`
  SentinelOne findings against the previous run.

## 2026-06-10 — v0.16.0 Agent Compliance v1 foundation

**Why:** The existing PowerShell compliance report needs to become an
always-on platform feature: collect all platform observations every few
hours, evaluate per-client required platform combos, surface the
current matrix in Metabase, and alert on actionable findings. Decision:
keep v1 inside `ninja-dashboard` to reuse Postgres, Metabase, and the
existing Portainer deployment pattern instead of duplicating a stack.

**Done:**
- Added `AGENT_COMPLIANCE_PROPOSAL.md` and rewrote `BLUEPRINT.md` for
  the v1 scope.
- Added migration `019_agent_compliance.sql` with the
  `ninja_agent_compliance` schema: clients, platform sources, aliases,
  requirements, notification routes, alert rules, suppressions, source
  runs, observations, current/history matrix, findings, alert state,
  alert events, and first-pass dashboard views.
- Added `ingest/agent_compliance/`:
  - Ninja observation source reads existing `ninja_core` tables.
  - SentinelOne, LogMeIn, and ScreenConnect collectors call native APIs.
  - ScreenConnect is modeled as per-client sources.
  - Matrix builder evaluates required platforms per client/device type.
  - Source failures/unconfigured required sources become unknown/source
    conditions rather than false missing-agent findings.
  - Alert delivery supports webhook, SMTP email, and Zendesk requests.
- Split schedules in `ingest/main.py`:
  - patch/Ninja ingest remains the default `/run` path.
  - added `/run/patches`.
  - added `/run/agent-compliance`.
  - added `AGENT_COMPLIANCE_ENABLED` and
    `AGENT_COMPLIANCE_SCHEDULE_HOURS`.
- Added an Agent Compliance Metabase bootstrap module that creates a
  separate `Agent Compliance` collection and command-center dashboard.
- Updated `.env.example`, `CONTEXT.md`, `CHANGELOG.md`, `VERSION`, and
  `TODO.md`.

**Validation:**
- `python -m compileall ingest` passes.
- Runtime import check could not run locally because project
  dependencies are not installed in this Windows Python environment
  (`python-dotenv` missing).
- Migration/live DB smoke was not run because local `psql`/`docker`
  commands are unavailable in this shell.

**Pending:**
- Apply migration 019 on the live stack.
- Configure platform source rows and host `.env` secrets.
- Trigger `/run/agent-compliance`.
- Verify source health, matrix rows, active findings, dashboard
  bootstrap, and one alert route.

## 2026-06-05 — v0.15.0 never-patched fix + driver-category exclude

**Why:** Troubleshooting session on device 4042 found ~6 devices
fleet-wide misclassified as Never-Patched. Root cause: Ninja's
`/queries/os-patch-installs` returns INSTALLED rows without
`installedAt` for some historical / OS-applied patches. The
`device_patch_signal` MV filtered `installed_at IS NOT NULL` at
source, so those devices disappeared from the signal and
classification logic concluded "never installed." Separately, the
operator wanted to hide DRIVER_UPDATES from every patch-context view
since they're not in scope for installs yet.

**Done:**
- Wrote `sql/migrations/016_install_signal_and_patch_category.sql`:
  - Rebuilt `device_patch_signal` to expose `ever_installed bool`
    alongside `last_seen_at` (still `MAX(installed_at)`). Dropped
    the source `IS NOT NULL` filter.
  - Added `patch_category` column to `current_patch_state` and
    `latest_install_outcome` (sourced from `patch_facts.type`).
  - Drop+recreated `device_troubleshooting_signal` (mig 015 body)
    with `patch_status`, `issue_type`, and `suggested_action` CASE
    blocks updated to read `dps.ever_installed`. Added explicit
    branches for `'Stalled (install dates missing)'`.
- Added `DASHBOARD_PATCH_CATEGORIES_EXCLUDE` setting to
  `ingest/config.py` and documented it in `.env.example`. Default
  `DRIVER_UPDATES`. Empty value disables the exclusion.
- In `ingest/metabase_bootstrap.py`:
  - Added module-level `EXCLUDE_PATCH_TYPES`,
    `_PATCH_TYPE_EXCLUDE` (for MV-based CTEs), and
    `_PATCH_TYPE_EXCLUDE_RAW` (for raw `patch_facts` CTEs).
  - Threaded the exclude fragment into every patch-context CTE:
    `_COMPLIANCE_CTES` and its three inline duplicates, all `cmd_*`
    / `patches_*` / `org_*` scalar+table cards, both Patch Detail
    shared CTEs (`_CTE_CURRENT_STATE`), Device Drilldown Patch
    State / Install History, Trends installs/failures per day, the
    daily-compliance helpers, Awaiting-Reboot last-install CTE,
    Org Overview client tables, etc.
  - Swapped `dps.last_seen_at IS NULL → NOT COALESCE(dps.ever_installed,
    FALSE)` everywhere classification runs (5 spots in scalar/count
    helpers, 1 in trends per-day, 1 in `cmd_clients`, 1 in
    `_PCOV_CTE`, 1 in `_problem_devices_cte`).
  - Surfaced `Type` column on Device Drilldown's Patch State
    History and Install History tables.
- Updated `CONTEXT.md` with two new sections: "Patch category
  exclusion" and "Never-patched vs install-dates-missing".
- Bumped `VERSION` to 0.15.0 (compliance counts shift +
  new env-var default).

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Smoke tests deferred until next ingest cycle on real DB; expected:
  - `SELECT ever_installed, last_seen_at FROM
    ninja_patches.device_patch_signal WHERE device_id = 4042;` →
    `ever_installed = TRUE`, `last_seen_at IS NULL`.
  - `issue_type` for device 4042 in
    `device_troubleshooting_signal` should read
    `'Stalled (install dates missing)'`.
  - `SELECT COUNT(*) FROM ninja_patches.device_patch_signal WHERE
    ever_installed AND last_seen_at IS NULL;` → ~6.
  - Driver rows hidden from every patch card; raw `patch_facts`
    counts unchanged.

**Open follow-ups (parked in TROUBLESHOOTING.md):**
- `ninja_core.devices.needs_reboot` column missing — separate fix.
- `installed_at = 2010-11-20` outlier sanity check.
- `INGEST_PATCHING_ENABLED_POLICIES` wire-up audit.
- Dead code: `_PATCH_SCOPE_CTE` (line 224 of
  `metabase_bootstrap.py`) is defined but never referenced —
  separate cleanup.

## 2026-06-04 — handy commands reference added

**Why:** The same host, ingest, Metabase, Postgres, probe, and SQL
commands kept recurring across sessions. A single reference file makes
the operational workflow easier to recover without rereading the whole
history.

**Done:**
- Added `HANDY_COMMANDS.md` at the repo root.
- Collected the recurring commands from the repo history and existing
  operator docs.

**Validation:**
- Documentation-only change. No code paths changed.

## 2026-06-04 — custom-fields ingest moved to scoped feed

**Why:** Device-only custom-field ingest was missing organization and
location values, and the operator now wants a small allowlisted set of
patching-exception fields plus the earlier enrichment fields.

**In progress:**
- Switched `ingest/core/custom_fields.py` to
  `/queries/scoped-custom-fields`.
- Passed `INGEST_CUSTOM_FIELDS_INCLUDE` through to the API as the
  `fields` filter.
- Kept device / organization / location pivoted views in sync.
- Updated `probe_fields.py` to inspect the scoped feed instead of the
  legacy device-only report.

**Validation so far:**
- Probe confirmed `scope=ORGANIZATION` and `scope=NODE` records are
  returned from `/queries/scoped-custom-fields`.
- Probe confirmed the new exclusion fields come through on both org
  and device records.

**Pending:**
- Update the release docs and commit hash once the code is finalized.
- UI/dashboard wiring for the new custom-field filters is still a
  separate pass.

## 2026-06-04 — v0.14.10 align Org + Trends visible labels to patching-device KPI

**Why:** The Org Overview bars and Trends line still showed the old
`Fully patched devices %` wording even after the KPI formula was
clarified.

**Done:**
- Renamed the Org Overview bar chart labels to
  `Fully patched % (patching devices)` by device type / operating
  system.
- Renamed the Trends line to
  `Fully patched % (patching devices) per Day`.
- Left Command Center alone.

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Commit `be63e7e` created for the label alignment.

## 2026-06-04 — v0.14.9 clarify fully-patched KPI as patching-device subset

**Why:** The second KPI title looked like fleet-wide compliance even
though the intended denominator is the actively patching subset.

**Done:**
- Renamed the visible card to `Fully patched % (patching devices)`.
- Rewired the card formula so it measures fully patched among devices
  that are actively patching.
- Updated `CONTEXT.md` to make the denominator explicit.

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Commit `148de4e` created for the KPI clarification.

## 2026-06-04 — v0.14.8 fix bootstrap import error for active-patching KPI

**Why:** The `Actively patching %` helper was calling `_PCOV_CTE`
before that symbol existed at import time, which prevented
`ingest.metabase_bootstrap` from loading.

**Done:**
- Inlined the device-classification CTE into
  `_active_patching_scalar_query()`.
- Verified `python -m py_compile ingest/metabase_bootstrap.py` passes.

**Validation:**
- Commit `ba55729` created for the import fix.

## 2026-06-04 — v0.14.7 split patch KPIs into active-patching + fully-patched

**Why:** The prior dashboard wording still mixed the operator's scope
with compliance/progress language. The clearer MSP view is: how many
active devices are patching, and how many are fully patched.

**Done:**
- Command Center now headlines `Actively patching %` and keeps the raw
  count cards.
- Overall Status and Org Overview now show `Actively patching %` and
  `Fully patched devices %`.
- Trends now show `Fully patched devices % per Day` and
  `Patching Devices per Day`.
- `CONTEXT.md` terminology updated to match the new operator split.

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Commit `52c22e6` created for the operator KPI split.

## 2026-06-04 — v0.14.6 split device compliance from patch progress

**Why:** The old `Patch Compliance` label was ambiguous for an MSP
operator. The dashboards needed to separate "are devices fully patched
right now?" from "how much patch work has been installed so far?"

**Done:**
- Command Center now shows a single `Devices Compliant %` KPI.
- Overall Status and Org Overview now split into `Devices Compliant %`
  and `Patch Progress %`.
- Detailed org cards now use `Patch Progress` wording instead of
  `Patch Compliance`.
- Trends gained daily KPI cards for `Devices Compliant %` and `Patch
  Progress %`.

**Validation:**
- `python -m py_compile ingest/metabase_bootstrap.py` passes.
- Commit `fafe234` created for the dashboard split.

## 2026-06-04 — v0.14.5 add device reachability to Device Summary

**Why:** User wanted current up/down state surfaced next to `Last
Contact` in the Device Summary table so the difference between
freshness and reachability is visible at a glance.

**Done:**
- Added `Online?` to the Device Summary table in Device Drilldown.
- Value is derived from the latest snapshot's `offline` flag and
  rendered as `Yes` / `No` / `Unknown`.

**Validation:**
- Pending compile-check after the edit.

## 2026-06-04 — v0.14.4 stop Metabase card reuse by title

**Why:** v0.14.3 fixed the visible tag/mapping mismatch, but the
operator-reported behavior still pointed to stale card wiring. The
bootstrap was upserting cards by display name, and multiple dashboards
reuse titles like `Active Devices` / `Current Patch State`, so later
dashboards could overwrite earlier cards.

**Fix:**
- Added a hidden stable card UID (`ninja-dashboard:<dashboard>:<key>`)
  and wrote it into card `description`.
- `_upsert_card()` now matches on that UID instead of title.
- Existing duplicate-title cards in Metabase are left alone; future
  bootstraps create/update the correct card object for each dashboard.

**Validation:**
- `python -m py_compile` passes.
- Commit `fdaca32` created for the Device Summary change.
- Commit `2779967` pushed to `origin` and `a-m-rose`.

## 2026-06-04 — v0.14.3 fix device-card filters via mapping/tag parity

**Why:** User reported Command Center / Overall / Org device
cards don't honor filters even after v0.14.1 + v0.14.2 wired them.

**Diagnosis:** Compared declared template tags vs
`parameter_mappings` per card. Patch Detail (which works) has 8
tags and 8 mappings — exact parity. CC / Overall / Org Overview /
Trends device cards declared the FULL tag set but mapped only a
subset (skipping severity). Pattern: mismatched cards silently
break ALL filter binding, not just the missing one.

**Fix:**
- Replaced `_*_PARAM_MAPPINGS` with `_*_PARAM_MAPPINGS_FULL` on
  every card on the four affected dashboards via four `replace_all`
  edits.

**Open:**
- PCOV reports the same symptom but its tags == mappings == 5
  already. Need to inspect actual Metabase API response if v0.14.3
  doesn't resolve PCOV too. Will be v0.14.4 if necessary.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.14.2 Overall + Trends filter expansion + Org multi-select

**Done:**
- Overall Patching Status: Org + OS Family + Severity added
  (multi-select); every card re-wired with org JOIN + appropriate
  filter fragment.
- Trends: Org + Severity added; every card joined to
  organizations; patch-counting cards honor severity, device-
  population cards skip it.
- Org dropdown converted to multi-select on Detail, Org Overview,
  PCOV. SQL predicates rewritten from `o.name = {{var}}` to
  `o.name IN ({{var}})`.

**Decision documented:**
- Compliance scalars (overall_compliance, compliance_worst,
  compliance_all) honor Org + Device Type + OS Family but skip
  Severity. Compliance is the fleet-wide coverage number;
  scoping by severity would change its semantic to "% of
  Critical installed". Defer until requested.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.14.1 Patch Command Center filter set expanded

**Why:** User reported "cards on Command Center don't follow
filters" and asked for high-level dashboards to have richer filter
sets. Per the blueprint-first rule, wrote BLUEPRINT.md with
proposed filter set per dashboard, user confirmed.

**Audit:** every Command Center card was correctly wired for the
existing Device Type filter (template_tags + param_mappings +
predicate fragment in SQL). User-reported breakage most likely a
stale Metabase state from before v0.13.6.

**Done (Command Center only):**
- Added Org + Severity dropdowns (all 3 multi-select).
- `_CMD_TAGS` / `_CMD_PARAM_MAPPINGS_FULL` / new filter fragments
  mirror the existing Org Overview pattern.
- All 13 cards re-wired with org JOIN where missing, severity
  added to CTEs where needed, and the appropriate filter fragment
  in the outer WHERE.
- `cmd_clients` filters severity at CTE level to preserve LEFT
  JOIN semantics — filtering severity in the outer WHERE would
  silently drop devices.
- `build_command_parameters` now takes `org_names`; build_
  dashboards passes it through.

**Pending in same task (v0.14.2):**
- Overall Patching Status filter expansion (Org + OS Family +
  Severity).
- Trends filter expansion (Org + Severity).
- Convert remaining Org dropdowns (Detail, Org Overview, PCOV) to
  multi-select.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.14.0 filter audit clean + Needs Reboot demoted

**Why:** Operator wanted (1) confidence the v0.13.9 bug pattern
wasn't repeated on other dashboards, and (2) Needs Reboot demoted
from a top-row KPI because in a patch-ops context it's an action
signal, not a high-level KPI.

**Audit:**
- Shape A (declared-but-not-filtered): clean across every
  dashboard. Earlier "MISSING" hits in the audit script were
  false positives — nested dict keys (`id`, `display-name`) and
  timeline-window params (`days`, `pcov_days`) that each card
  consumes via its own CTE rather than the shared fragment.
- Shape B (inlined `[[AND` outside shared fragments): clean.
  Every `[[AND` lives in a fragment constant. `_DEVICE_FILTER`
  for Drilldown is the intentional exception (hard-binds the
  single selected device).
- Found one self-inflicted bug from v0.13.9: a duplicate
  `[[AND d.system_name = {{device}}]]` in `_FILTER_PREDICATES`
  (added at top without noticing it was already at the bottom).
  Removed.

**Layout:**
- Removed `cmd_reboot`, `overall_reboot`, `org_reboot` scalars.
- Reflowed Devices row on Command Center / Overall / Org from
  5 tiles at 5+5+5+5+4 to 4 tiles at 6+6+6+6.
- Removed the three keys from `_SCALAR_ALERT_RULES`.
- Tables and Trends chart untouched.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.13.9 Patch Detail filters reach every card

**Why:** Operator noticed that on Patch Detail not every card
narrowed when filters changed. Patch Detail is *the* filterable
workhorse — every card on it must honor every filter.

**Diagnosis:**
1. `_FILTER_PREDICATES` declared every filter except Device. So
   the Device dropdown was wired at the parameter level but never
   reached any card's SQL.
2. `detail_installs_timeline` inlined its filter predicates
   instead of using `_FILTER_PREDICATES`. The inlined version
   still used `= {{var}}` syntax, so v0.13.8's multi-select
   conversion missed it.

**Done:**
- Added `[[AND d.system_name = {{device}}]]` to
  `_FILTER_PREDICATES`.
- Replaced the inlined predicate block in
  `detail_installs_timeline` with `{_FILTER_PREDICATES}` so the
  timeline benefits from future filter changes automatically.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.13.8 multi-select filters + REJECTED audit note

**Why:** Operator wanted multi-select dropdowns ("show me MANUAL +
DELAYED at once") and a clear answer to "where do I see REJECTED"
now that v0.13.7 excluded REJECTED/DELAYED from the compliance
score. Following the new blueprint-first rule.

**Done:**
- New `_param_multiselect` helper (sets `isMultiSelect: True`).
- Converted dropdowns on Patch Detail, Org Overview, Device
  Patching Status, Command Center, Overall, Trends per the
  blueprint scope. Organization/KB/Device/Days stay single-select.
- Predicate fragments updated from `= {{var}}` to `IN ({{var}})`
  across `_FILTER_PREDICATES`, `_PCOV_FILTERS`, the four
  `_ORG_FILTER_*`, and the three single-dashboard filter snippets.
- Added "Where to find REJECTED patches" section in CONTEXT.md
  pointing at the Current Patch State pie click-through, the
  Patch Detail Status filter, and the compliance_all Rejected
  column. No new tables or scalars — operator confirmed existing
  surface is enough.

**Honest caveats:**
- `isMultiSelect: True` JSON shape varies by Metabase version.
  Documented but first time used here. If a dropdown still
  behaves single-select after rebuild, that's the JSON to debug.
- Substitution semantics for multi-select category type → comma-
  separated quoted strings in the SQL substitution — documented
  Metabase behavior, first use here.

**Validation:**
- `python -m py_compile` passes after every edit.

## 2026-06-04 — v0.13.7 compliance formula clarified + BLUEPRINT.md process

**Process change:**
- Updated `Development/DEVELOPMENT.md` with Agent Work Rule #5:
  blueprint before building. Non-trivial tasks must start with a
  `BLUEPRINT.md` at the project root. Used this task as the first
  to follow the rule.

**Done:**
- Defined the Patch Compliance formula in code (constants +
  `_COMPLIANCE_CTES` block) and in `CONTEXT.md` (glossary
  section). Single source of truth.
- REJECTED and DELAYED now excluded from both numerator and
  denominator on every compliance card. APPROVED / MANUAL /
  FAILED / PENDING counted as missing.
- Rewrote 6 compliance cards: overall_compliance, org_compliance,
  compliance_worst, compliance_all, org_device_type, org_os_family.
- compliance_all gained a "Compliance-Scope Patches" column so
  operator can see the denominator alongside the full "Total
  Patches" (including excluded REJECTED/DELAYED).

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.13.6 Device Type filter on Command Center, Overall, Trends

**Done:**
- Added Device Type (Server vs Workstation) filter as a top-of-page
  dropdown on:
  - Patch Command Center
  - Overall Patching Status
  - Trends
- Org Overview, Patch Detail, Device Patching Status already had
  it. Drilldown intentionally skipped.
- For each new filter: dedicated `PARAM_X_CLASS` + `_X_TAGS` +
  `_X_PARAM_MAPPINGS` + `_X_DEVICE_TYPE_FILTER` SQL fragment.
- Each card on the three dashboards updated: `template_tags` +
  `param_mappings` keys added, SQL predicate fragment appended.
- Patch-count CTEs that didn't expose device_id (e.g. cmd_approved,
  cmd_failed) updated to include device_id; outer SELECT joins
  ninja_core.devices.

**Why three separate filter declarations** rather than one shared:
Metabase parameter IDs are dashboard-scoped — same `p_*` ID
shouldn't be reused across dashboards. Keeping them distinct
avoids parameterMapping collisions on cross-dashboard click_behaviors.

**Validation:**
- `python -m py_compile` passes on the full module after every
  edit.

## 2026-06-04 — v0.13.5 Command Center Stalled Devices orphan removed

**Why:** Same orphan we cleaned up on Org Overview in v0.11.4 was
still on Command Center — half-width Stalled Devices table next to
Manual and Delayed Patches. The cmd_stale scalar already covers
the count, and clicking it drills into Device Patching Status.

**Done:**
- Removed `cmd_patch_activity_queue` card.
- `cmd_approval_queue` size_x bumped from 12 to 24 (full width).

**Validation:**
- `python -m py_compile` passes.
- Grep confirms `cmd_patch_activity_queue` is no longer in the file.

## 2026-06-04 — v0.13.4 compliance-by-X chart fixes + % suffix

**Done:**
- Fixed Org Overview's "Patch Compliance by Device Type" and
  "Patch Compliance by Operating System" charts. Two bugs:
  (a) compliance numerator counted INSTALLED against the
  patch_state CTE — never matched; (b) GROUP BY o.name produced
  multi-row groups so the chart was blank when no org filter.
  Rewrote queries to use install_outcome math and dropped o.name
  from SELECT/GROUP BY.
- Same `GROUP BY o.name` fix on the org_status pie.
- Added `_SCALAR_SUFFIX_RULES` table + `_apply_scalar_suffixes`
  post-processor — patterned after the alert-color one. Wired
  "%" suffix onto overall_compliance + org_compliance scalars.

**Validation:**
- `python -m py_compile` passes.

**Up next:** v0.13.5 Server vs Workstation global filter on
Command Center, then v0.13.6 the same on Overall Status + Trends.

## 2026-06-04 — v0.13.3 scalar alert coloring

**Done:**
- New `_alert_color()` helper builds the column_formatting JSON
  for a single threshold rule.
- `_SCALAR_ALERT_RULES` dict declares which card keys get which
  color rules (red for failed/never-patched, amber for
  stalled/manual/reboot).
- `_apply_scalar_alerts()` post-process step walks each card list
  after definition and merges the rules into each card's
  viz_settings.column_settings.

**Honest caveat:**
- First time provisioning Metabase `column_formatting` via API in
  this codebase. JSON shape from docs; varies by Metabase version.
  If a scalar shows no color after rebuild, that's where to look.

**Deferred:**
- Patch Compliance range coloring (red < 80% / amber 80-95% /
  green ≥ 95%) — start with simple "non-zero = alert" first.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.13.2 backfill CLI + dashboard JSON export

**Done:**
- `ingest/activities/backfill.py` — one-shot CLI to walk
  /v2/activities backward via olderThan from the oldest id in DB.
  Filters via the same TYPES_INCLUDE / SOURCES env vars as the
  forward ingest. Stops at --days cutoff, --max-pages, or SIGINT.
  Idempotent inserts.
- `ingest/metabase_export.py` — CLI to fetch each Ninja-collection
  dashboard's JSON via /api/dashboard/<id> and write pretty-printed
  to metabase/dashboards/<slug>.json. Reuses the bootstrap's auth
  + password helpers.

**Validation:**
- `python -m py_compile` passes on both new modules.

## 2026-06-04 — v0.13.1 Trends dashboard

**Done:**
- New DASH_TRENDS = "Ninja — Trends" dashboard with 5 time-series
  cards: installs/day, failures/day, reboots/day, active devices/
  day (line), and currently-MANUAL patches by age week.
- Trends placed in nav order between Device Status and Patch
  Detail.
- All cards take a single "Timeline window (days)" parameter
  defaulting to 90 (except the MANUAL-age card which is a
  snapshot of current state).
- No schema changes — every metric is derived from existing
  timestamps (installed_at, activity_time, snapshot_at,
  first_observed_at).

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.13.0 Command Center: awaiting-reboot + fleet activity feed

**Done:**
- Added `cmd_awaiting_reboot` table — INSTALLED patches × device
  needing reboot × no SYSTEM_REBOOTED activity since install.
- Added `cmd_recent_activity` table — fleet-wide patch+reboot
  activity stream (last 100), filtered to the canonical allowlist.
- Hoisted `_DRILLDOWN_ACTIVITY_CODES` and the SQL constant to the
  top of the file so they resolve before COMMAND_CARDS uses them.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.12.7 stale-data banner on Overall Status

**Done:**
- Added Data Freshness scalar on Overall Patching Status. Shows
  minutes since last successful run, switching to "STALE — N h"
  format past a 3-hour threshold.
- Patch Compliance scalar shrunk from full-width (24) to size 18
  to make room.

**Validation:**
- `python -m py_compile` passes.

**Still queued (this batch was paused mid-stream):**
- "Patches installed awaiting reboot" panel on Command Center.
- Fleet-wide "Recent Patch Activity" feed on Command Center.
- Trends dashboard (whole new dashboard).
- Scalar background coloring.
- Activities backfill CLI.
- Dashboard JSON export tool.

## 2026-06-04 — v0.12.6 Drilldown activity feed allowlist

**Why:** User reported the Device Drilldown's "Recent Activity"
card was showing non-patch / non-reboot rows. The card had no
SQL-side filter — it trusted the ingest's TYPES_INCLUDE.

**Done:**
- Defined `_DRILLDOWN_ACTIVITY_CODES` = the canonical patch-
  lifecycle codes + `SYSTEM_REBOOTED`.
  `PATCH_MANAGEMENT_MESSAGE` deliberately excluded (noisy info).
- Added `WHERE a.activity_type IN (...)` to the device activity
  card's SQL.
- Renamed the card to "Recent Patch & Reboot Activity" so the
  scope is obvious.
- Ingest unchanged — broader rows still land in
  `ninja_activities.activities`; the dashboard just filters
  what it shows.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.12.5 section header dividers

**Done:**
- Added `SECTION_HEADER_HEIGHT = 1` constant and
  `_section_header_dashcard` helper (Metabase virtual text
  dashcard with markdown content).
- Extended `_set_dashboard_layout` with an optional
  `section_headers` parameter. The shift() closure walks the
  sorted headers and bumps every card at or below each header's
  row down by `SECTION_HEADER_HEIGHT`. Header cards land at their
  own shifted positions (orig_row + count of prior headers).
- `build_dashboards` declares headers per dashboard; pass 1b
  threads them through.
- Applied to Command Center, Overall Patching Status, Org
  Overview — the three dashboards that follow the canonical
  Compliance / Devices / Patches grouping. Drilldown, Patch
  Detail, Device Patching Status didn't receive headers; they
  don't have the scalar grouping pattern.

**Honest caveat:**
- First time provisioning Metabase virtual text dashcards in the
  middle of a layout (nav bar was the first; that's at the top).
  JSON shape mirrors the nav bar's, so high confidence. If the
  layout PUT 4xx's, check the bootstrap logs.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.12.4 pie / bar color coding

**Done:**
- Defined two shared palettes near the top of the bootstrap:
  `PATCH_STATE_COLORS` and `PATCH_ACTIVITY_COLORS`.
- Applied `pie.colors` to all 4 Current Patch State pies (Overall
  Status, Patch Detail, Drilldown, Org Overview) and to the PCOV
  Patching Status pie.
- Applied `series_settings.<series>.color` to the PCOV stacked OS
  bar so all three series (Patching / Stalled / Never-Patched
  Devices) render in green / amber / red consistently.

**Deferred:**
- Section header markdown dividers — programmatic row-shift
  refactor pending.
- Scalar background coloring — Metabase conditional-formatting
  JSON shape varies by version; would test live first.

**Up next:** v0.12.5 will attempt section headers (in a separate
commit since the JSON shape is risky). Then the activity-feed
cleanup user just asked about.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.12.3 canonical scalar set + Org severity

**Done:**
- Added Needs Reboot scalar to Overall Patching Status.
- Added Patching Devices and Needs Reboot scalars to Org Overview.
- Wired severity filter to the 5 remaining Org Overview patch
  scalars (failed, approved, manual, delayed, status pie) by
  adding `severity` to each CTE and swapping their predicate from
  `_ORG_FILTERS_DEVICE` to `_ORG_FILTERS_PATCH_CS` /
  `_ORG_FILTERS_PATCH_LIR`. param_mappings updated to
  `_ORG_PARAM_MAPPINGS_FULL`.
- Row 4 layouts on Overall + Org reflowed to 5 tiles at
  5+5+5+5+4 to match Command Center.

**Still deferred to v0.12.4:**
- Section header markdown cards between scalar groups.
- Color coding.
- Severity wiring on org_compliance / org_device_type /
  org_os_family — those compute compliance % across a population;
  severity filtering there changes semantic (it'd be "% installed
  among critical patches"). Skipping unless requested.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-04 — v0.12.2 Patch History split + Org filter wiring

**Done:**
- Replaced `device_patch_history` (Device Drilldown) with two
  separate tables: `device_patch_state_history` (Patch State
  History) and `device_install_history` (Install History). Resolves
  the v0.12.1-reported commingling — the old table mixed
  `fact_type='patch_state'` and `fact_type='install_outcome'`
  rows under a single "Current Patch State" column header that
  meant different things on different rows.
- Wired every Org Overview card's SQL to honor Organization +
  Device Type + OS Family filters via `_ORG_FILTERS_DEVICE`.
  Severity additionally honored on the two patch tables
  (`org_failed_queue`, `org_action_queue`) via
  `_ORG_FILTERS_PATCH_LIR` / `_ORG_FILTERS_PATCH_CS`.
- Converted relevant Org card queries from plain triple-quote
  strings to f-strings so the filter helpers interpolate.

**Validation:**
- `python -m py_compile` passes.

**Still deferred:**
- Section header markdown cards between scalar groups.
- Color coding.
- Adding Patching Devices scalar to Org Overview, Needs Reboot
  scalar to Overall Status / Org Overview.
- Severity filter wired on remaining patch scalars (requires CTE
  rewrites).

## 2026-06-03 — v0.12.1 card grouping + Org filter scaffolding

**Done:**
- Reordered scalars on Command Center, Overall Patching Status, and
  Org Overview into the canonical groupings:
    - Devices row: Active · Patching · Stalled · Never-Patched
      (+ Needs Reboot on Command Center).
    - Patches row: Approved · Manual · Delayed · Failed.
- Added a full-width Patch Compliance headline scalar to Overall
  Patching Status. Moved Org Overview's existing Patch Compliance
  scalar to full-width at row 0 for visual prominence.
- Defined Org Overview filter widgets (Device Type, OS Family,
  Severity) and SQL predicate helpers (`_ORG_FILTERS_DEVICE`,
  `_ORG_FILTERS_PATCH_CS`, `_ORG_FILTERS_PATCH_LIR`, and "no_class"
  / "no_os" variants for the per-axis charts).

**Deferred to v0.12.2:**
- Per-Org-card SQL wiring to the new filters. The dropdowns appear
  but cards still query unfiltered data.
- Section header markdown cards between groups.
- Color coding.
- Adding Patching Devices scalar to Org Overview and Needs Reboot
  scalar to Overall Status / Org Overview to fully match the
  canonical scalar set.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-03 — v0.12.0 dashboard renames + Command Center homepage

**Done:**
- Renamed Fleet Overview → "Overall Patching Status" (it's a
  fleet-wide rollup of compliance + state breakdowns).
- Renamed PCOV "Patching Status" → "Device Patching Status" (it's a
  per-device classification). The "Patching Status" name was
  overloaded and operator-confusing.
- Both renames use the existing legacy_names rename-in-place
  mechanism, so dashboard IDs survive the rename. Nav bar labels
  shortened to "Overall Status" / "Device Status".
- Active Devices moved to leftmost position on Device Patching
  Status row 0 for visual consistency with the other dashboards.
- Bootstrap now sets Patch Command Center as Metabase's
  instance-wide custom homepage via /api/setting/custom-homepage
  + /api/setting/custom-homepage-dashboard. Best-effort: warns and
  continues on Metabase API rejection.

**Deferred to v0.12.1:**
- Org Overview filter additions (Device Type, OS Family, Severity)
  with all org cards rewired to honor them.
- Card grouping pass (device cards together, patch cards together,
  section header markdown cards).
- Patch Compliance placement as a top-level KPI on Fleet/Org.

**Validation:**
- `python -m py_compile` passes.

## 2026-06-03 — v0.11.4 full click-thru audit + Org Overview cleanup

**Done:**
- Audit pass: 11 remaining tables converted from quoted-display-
  alias click_behavior pattern to lowercase-snake_case unquoted.
  Per the v0.10.2/v0.11.3 lesson, Metabase reliably matches
  per-column click_behaviors only when the key string matches a
  stable unquoted column identifier in the SQL output.
- Removed orphan `org_patch_activity` table (Stalled Devices on
  Org Overview).
- `org_action_queue` (Manual and Delayed Patches on Org Overview)
  reflowed to full width.

**Validation:**
- `python -m py_compile` passes.
- Grep for `"[A-Z]\w*":\s*\{"target"` in `column_click_behaviors`
  returns zero — no leftover capitalized keys.

## 2026-06-03 — v0.11.3 needs_reboot click misalignment

**Why:** After v0.11.2, user retested. Most click-thrus now work:
- compliance_all org click → Org Overview ✓
- cmd_clients org click → Org Overview ✓
- needs_reboot device → Drilldown ✓
- needs_reboot device_type → Detail ✓

BUT:
- needs_reboot org click → does nothing
- needs_reboot last_contact → navigates to Org Overview (wrong)

**Hypothesis:** Pattern fingerprint = click_behaviors misaligned
to columns. last_contact's inert self-link (which should reload the
current dashboard) is somehow getting the organization-column
behavior, while organization gets the inert. Root cause likely two
overlapping factors:
- `d.last_contact` had no explicit `AS` alias, so Metabase may
  identify the column differently than its sibling columns and
  fall out of sync with our `["name","last_contact"]` key.
- Inert self-link placeholders on info columns were the v0.7.4
  experiment to suppress the default drill popup; turns out they
  cause more confusion than they prevent.

**Done:**
- Removed inert placeholders from `needs_reboot` (Fleet) and
  `org_reboot_devices` (Org). Info columns now show the default
  Metabase drill popup again — that's the lesser evil compared to
  click_behaviors getting reassigned to wrong columns.
- Gave every column on those tables an explicit lowercase `AS`
  alias.
- `org_reboot_devices` had also been left with the capitalized
  quoted alias pattern from v0.10.0 humanization; converted to the
  same lowercase-snake_case pattern as `needs_reboot`.

**Validation:**
- `python -m py_compile` passes.
- Operator retest after Portainer rebuild will confirm.

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

**Current dashboard pass:**
- Patch-scope derivation now includes location-level custom-field
  inheritance in `v_active_devices`.
- Added compact count cards for `Actively patching` / `Fully patched`
  alongside the existing percentage KPIs.
- Reflowed the top-level dashboard rows so the new cards do not
  overlap the existing tiles.
- Optimized the Device Patching Status scope filter by carrying
  `patching_scope` into the classified device CTE instead of re-checking
  the active-device view row-by-row.
- Removed the remaining correlated `v_active_devices` scope filters
  from the Metabase bootstrap and moved the affected cards onto
  `ninja_core.v_active_devices` directly so `patching_scope` filters
  behave as ordinary column filters.
- Reflowed the Overall Status and Org Overview KPI bands so the percent
  cards, count cards, and Active Devices card sit in a compact top
  section.
- Added patch summary materialized views for current patch state,
  latest install outcome, and per-device patch signal; patch ingest now
  refreshes them after each run.
- Reworked the heavy Metabase cards to use those summary views instead
  of rebuilding latest patch state per card.
- Re-banded Overall Patching Status and Org Overview into compact
  Compliance, Devices, and Patches sections, and fixed the Trends
  patch-scope filter path for Patch Installs per Day.
- Materialized `ninja_core.v_active_devices` itself so patching scope,
  org, location, device type, and device-name filters use stored indexed
  columns instead of recomputing custom-field inheritance for every
  dashboard card.
- Added separate `Total Devices` cards to Command Center, Overall
  Patching Status, and Org Overview while preserving `Active Devices`
  as its own KPI immediately to the right.
- Fixed Device Drilldown `Device Summary` so dashboard filters are
  applied through a valid `WHERE 1=1` clause.
- Added current-inventory tracking for devices: full device ingest now
  marks devices missing from Ninja as non-current instead of deleting
  history, and current dashboard totals exclude non-current devices.
- Added a `Problem Devices - Triage Queue` table to Device Patching
  Status. It surfaces stalled/never-patched devices plus supporting
  cause signals such as offline state, reboot pending, failed installs,
  manual approvals, approved waiting patches, missing patches, and
  patching notes, with drillthrough to Device Drilldown.
- Added a dedicated Issues dashboard using the latest materialized
  current-device and patch-summary views plus `ninja_activities`
  activity-feed evidence. The issue queue filters by issue type,
  offline, reboot, failed installs, missing patches, and patch-started
  without completion; device rows drill into Device Drilldown.
- Added a materialized `ninja_activities.device_activity_signal` view so
  issue cards reuse one per-device activity summary instead of
  re-aggregating raw activity rows per card.
- Reordered navigation into the operational workflow and moved Trends
  to the end; added spaced bullet separators in the nav bar.
- Capped table card heights globally so operators can see several rows
  and still reach horizontal scrolling without paging down.
- Trimmed wide table cards so high-level queues show decision columns
  first while verbose evidence stays in Device Drilldown.
- Surfaced assigned policy in the Issues/triage workflow and Device
  Summary, with policy filters on Issues and Device Patching Status.
- Added `/queries/device-health` ingest design: stores health snapshots,
  latest health rollup, pending reboot reason, Ninja OS patch summary
  counts, alerts, active jobs, install issues, vulnerability counts, and
  product installation statuses for comparison against patch facts.
- Added `ninja_core.device_troubleshooting_signal` as a one-row-per-device
  materialized signal for issue/triage dashboards. It combines patch facts,
  activity evidence, health counts, policy, scope, and current device metadata
  once per ingest run so Issue and Device Status cards do not re-aggregate the
  same raw tables independently.
