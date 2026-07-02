# Sessions

Chronological dev journal. What was done each session, why decisions
were made, what's pending. Useful for resuming interrupted work.

---

## 2026-07-02 — v0.34.3 scalar click-through filter propagation

**Why:** Clicking Command Center's Patching Devices card navigated to
Device Status but did not carry the operator's current filters, so
`Device Type = Windows Server` was lost.

**Fix:** Replaced URL-only `pcov_status` presets on the patching,
stalled, and never-patched scalar cards with dashboard parameter
mappings. The scalar queries now expose a hidden `pcov_status` constant
for the target status while the click behavior propagates matching
source dashboard filters such as Client, Device Type, and Patching
Scope.

**Validation:** Local compile and generated click-behavior inspection
confirm Command Center `Patching Devices` maps `p_pcov_status` from the
card result and carries `p_cmd_class` into `p_pcov_class`.

---

## 2026-07-02 — v0.34.2 client/status patch dashboard buildout

**Why:** The first patch dashboard slice still sounded too formal and
too much like a health-scoring system. The desired behavior is simpler:
show whether a client or device needs action, why, and where to click
for the evidence.

**Decision:** Use client/status language across patch operations:
Client Patch Status, Triage, Patch Trends, Needs Action, Watch, and
Good. Keep lowercase `organization` SQL aliases where Metabase
click-through mappings depend on them, but show `Client` in visible
filter and table labels.

**What landed:**
- `BLUEPRINT.md` updated to the final functional-area model.
- Legacy dashboard titles are renamed in place with legacy card UID
  matching so bootstrap does not duplicate existing cards.
- Command Center client status rules were made explicit and stable.
- Client Patch Status retains the key click-through paths from client,
  device, patch state, KB, and device type columns.
- Triage now includes scan-gap, reboot, approval, and stalled-device
  subqueues in addition to message search and full failure text.
- Device Drilldown now surfaces the current problem, suggested action,
  recent install/failure timing, and full failure/warning messages.

**Pending validation:**
- Run Metabase bootstrap against the stack.
- Measure landing-page load times against the <4s cold / <3s filtered
  target.
- Walk the Client Patch Status and Triage click-through paths with live
  data.

---

## 2026-07-01 — v0.34.1 patch dashboard functional blueprint

**Why:** The patch dashboards had the data to answer operational
questions, but the first read still felt like disconnected counts. The
desired view is functional, not role-based: Command Center for
cross-customer health, Customer Health for one customer, Triage for
device work, Device Drilldown for evidence, and Trends/Reporting for
movement.

**Decision:** Keep Metabase and preserve stored dashboard identities /
click-through behavior. Rename visible navigation labels only:
`Org Overview` becomes Customer Health and `Issues` becomes Triage.
Use the existing `device_troubleshooting_signal` materialized view for
the first implementation slice so landing cards stay fast without a new
migration unless validation proves one is needed.

**What landed:**
- `BLUEPRINT.md` rewritten as the locked patch-operations dashboard
  blueprint.
- Command Center `Clients Needing Attention` now ranks customers by
  health tier and reason.
- Customer Health top band now shows health tier, patching-enabled
  devices, successful scans in 30d, recent installs in 30d, and devices
  needing attention.
- Triage queue now exposes priority, blocker, full warning/failure
  message text, and includes warning-only devices.
- Triage filters now include `Message Contains` for finding multiple
  devices with similar errors.

**Pending validation:**
- Bootstrap Metabase on the stack and verify dashboard load time,
  click-through parameter propagation, and SQL execution against live
  data.

---

## 2026-06-18 — v0.32.0 id-link model + duplicate-client cleanup

**Why:** Operator renamed three customers in Ninja (PCHC, City
Painting via CPS, GF Supplies). Discovery was name-keyed: it saw the
new `platform_group_name` and minted three new `clients` rows
(1299, 1300, 1301) sitting alongside the old client_ids (22, 7, 10).
Filters showed both, matrix rows split, every renamed customer felt
"missing" on the platforms that had already caught up. Diagnostic
query against `platform_observations` confirmed the same Ninja
`platform_group_id` had been observed under two names — definitive
rename signature.

**Decision:** Stop using names as identity. Add a
`client_platform_links` table that maps
`(platform, platform_group_id, source_id)` → `client_id`. Discovery
consults it before name/alias matching. Aliases stay only for
cross-platform identity glue. Locked in BLUEPRINT.md: keep OLD
client_ids, auto-refresh `client_name` from upstream Ninja name on
every link match.

**What landed:**
- Migration 052 — `client_platform_links` table + unique index.
- Migration 053 — backfill links from observations, demote
  1299/1300/1301, rename clients 22/7/10/1273 to current Ninja
  names, drop duplicate matrix rows, close superseded
  org_candidates.
- `config_loader.py` — `load_id_links()`,
  `upsert_id_links_from_observations()`; `resolve_client_id()`
  consults links first; `sync_clients_from_observations()` skips
  auto-mint when (platform, group_id) is already linked.
- `ingest.py` — `_resolve_observations()` accepts id_links; after
  all sources resolve, links are upserted and `clients.client_name`
  is refreshed from Ninja; `clients` reloaded before matrix build so
  the new names propagate to `compliance_matrix_current` the same
  run.

**Verification plan (after Portainer redeploy):**
1. Apply migrations via the next `/run/agent-compliance`.
2. Confirm no `(platform, platform_group_id)` maps to multiple
   client_ids in the link table.
3. Confirm clients 22/7/10/1273 show the current names; 1299/1300/
   1301 are `enabled=false`, `source='demoted'`, zero matrix rows.
4. Spot-check Metabase customer filter — only the consolidated
   names appear.

**Side notes captured this session:**
- Multiple customers reported as missing across platforms are
  almost always upstream rename drift, not real enrollment gaps —
  the device alias proposal was rejected; id-link is the right
  level of abstraction.
- ScreenConnect's `GetSessionsByFilter` returns sessions with
  empty `GuestInfo.MachineName` when the session was created in
  the console with a pre-set name rather than enrolled cleanly.
  Affects ~2 of 960 UTA sessions; documented as an operator action
  item (rename session in SC console or re-enroll), not a code
  change.
- NJ3 case: confirmed NJ3 is enrolled in Ninja now; the SC session
  `YLSedison` for the same box has empty GuestInfo so it does not
  collapse with `nj3`. Out of scope for this session.

---

## 2026-06-16 — v0.28.0 Align breakdowns + filters with state model

**Why:** Operator hit two ergonomic problems on the new state model:
the `Needs attention by issue type` card had Missing/Offline columns
that duplicated information already on the row label; the `Needs
attention by customer` card had a `Review` column that read 0 across
the fleet because only `device_state='Review'` (degraded/unknown)
qualified, while the cross-customer ambiguity work was hidden under
the `needs_review` boolean on Missing rows. Filters on the Devices
and Alerts pages still used the pre-state-model vocabulary in
places.

**Done:**
- All four Today breakdowns and all four Devices breakdowns now read
  from `v_device_state_current`. Customer / OS family / Device type
  cards show `Missing | Offline | Stale | Review | Total` columns;
  `Review` is `device_state = 'Review' OR needs_review` and the
  other state filters add `AND NOT needs_review` so each device is
  counted once across the row. Issue type card collapsed to a single
  `Devices` count, with new rows for `No recent activity` (Stale)
  and `Missing — needs cross-customer review`.
- Scope extended to
  `device_state IN ('Missing','Offline','Stale','Review') AND NOT
  ignored` so visible totals reconcile to the KPI strip.
- Renamed `devices_missing_by_customer` card key →
  `devices_attention_by_customer`.
- Alerts page `Finding type` dropdown now uses
  `["Missing", "Offline", "Collector failed"]` instead of raw
  `*_required_platform` strings, and dropped the dead
  `cross_client_conflict` value (we stopped emitting these in
  v0.23.8). All seven card WHERE clauses on `{{finding_type}}`
  rewritten to translate via inline CASE so the dropdown labels map
  to the stored finding_type values.
- Devices page `NO AV` filter relabeled to `S1 exempt` (label only,
  underlying `s1_exempt` boolean logic unchanged).

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run, then visual sweep
  of the new breakdown columns; spot check that totals reconcile
  against the KPI strip; confirm Alerts page Finding type dropdown
  shows the friendly labels and filtering works.

## 2026-06-16 — v0.31.0 Add-source form for ScreenConnect

**Why:** Operator asked for a self-serve way to add a new
per-customer ScreenConnect tenant rather than hand-writing SQL.
The pattern already exists in the codebase
(`/agent-compliance/action/ignore-device` style HTML form), so
reuse it.

**Done:**
- New endpoint `/agent-compliance/action/add-source` (`/a/as`).
  GET without `confirm=1` returns an HTML form: customer dropdown
  populated from active clients, source slug (validated regex
  `[a-z0-9_]{2,40}`), display name, base URL. GET with `confirm=1`
  inserts `platform_sources` (`is_shared=false`, `source_key =
  sc_<slug>`, env var refs `SC_<SLUG>_EXT_GUID` /
  `SC_<SLUG>_SECRET_KEY`) and returns a success page with the env
  var names the operator must set on the host.
- Setup dashboard gets a
  `Add a per-customer ScreenConnect source` card under Routes and
  sources (row 36, col 12). Clicking the only cell opens the form.

**Design constraint preserved:**
- Secrets do not pass through the form. Only env var names are
  written to the DB. Real `EXT_GUID` / `SECRET_KEY` values stay
  in `/amr-ch-01_data/ninja-dashboard/.env` on the host.

**Out of scope for v1:**
- Ninja / SentinelOne / LogMeIn add-source forms. Those are
  typically shared sources, rarely added.

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run.
- Open Setup → click the new card → fill form → confirm the
  `platform_sources` row exists with the expected slug-based env
  var refs. Set env vars on host, redeploy, trigger collection,
  confirm a `source_runs` row with `status='ok'`.

## 2026-06-16 — v0.30.0 Unresolved evidence + macOS/Linux OS family

**Why:** Operator investigation on `RUBYPH-F020` showed it was
actively checking in to SentinelOne every few hours, but under
SentinelOne's `Default site` (no resolved client). Our cross-customer
review logic only joins `compliance_matrix_current`, which excludes
unresolved observations — so the device looked cleanly `Missing
SentinelOne` with no signal that the agent was running but
mis-mapped. The operator would never know to fix the SentinelOne
site assignment.

Separately, the operator asked whether Mac Ninja devices were being
ingested. They were (no platform filter in the agent_compliance
Ninja fetcher), but the `os_family` CASE only knew Windows, so all
Macs were bucketed as `Other` and invisible on the OS family
filter/breakdown.

**Done:**
- Migration 051 rewrites `v_device_state_current`:
  - New `unresolved_evidence` CTE joins recent
    `platform_observations` where `resolved_client_id IS NULL` and
    `norm_name` matches a device's `norm_name` for one of its
    `action_missing_platforms`. Exposes `unresolved_matches` (jsonb)
    and `unresolved_platforms` (text[]) at the end of the view.
  - `needs_review` and `review_reason` now also include the
    unresolved-evidence case. Operator sees
    `Found under unresolved group — fix site/alias mapping`.
  - `state_reason` for `Missing` devices appends `; also under
    unresolved (<platforms>) — fix site/alias mapping` when
    unresolved evidence exists.
  - `recommended_action` for that case reads `Fix the site/alias
    mapping so the unresolved observation maps to this customer`.
  - `os_family` CASE expanded with macOS major-version buckets
    (`macOS 10` through `macOS 15`, `macOS 26`, `macOS (other)`)
    plus a single `Linux` bucket.
- `OS_FAMILY_VALUES` in
  `ingest/agent_compliance/metabase_bootstrap.py` updated so the
  dashboard `OS family` dropdown lists the new buckets.

**Out of scope (follow-up):**
- Per-OS `required_platforms` overrides (e.g. Macs shouldn't
  require LogMeIn). Currently inherits the client's full list, so
  Macs may show false-positive Missing on LogMeIn.
- Linux variant breakdown (Ubuntu vs CentOS vs RHEL etc.).

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run.
- Spot-check `RUBYPH-F020`:
  `SELECT hostname, device_state, missing_platforms,
   unresolved_platforms, review_reason, state_reason
   FROM ninja_agent_compliance.v_device_state_current
   WHERE hostname = 'RUBYPH-F020';`
  Should now show `needs_review = true`,
  `unresolved_platforms = {SentinelOne}`, and the operator-facing
  text pointing at the unresolved SentinelOne site.
- Check OS family on Mac devices:
  `SELECT os_name, os_family, COUNT(*)
   FROM ninja_agent_compliance.v_device_state_current
   WHERE os_name ILIKE '%mac%'
   GROUP BY os_name, os_family;`

## 2026-06-16 — v0.29.1 Device rename detection

**Why:** Operator hit a "vanished device" mystery (`0115Y25`) and we
traced it to a bulk rename in Ninja — the device was now `ADH-RE03`
with the same `platform_device_id`. The system had the data to match
across renames but nothing recorded it, so the operator had to do a
manual cross-reference. Surfacing renames on Debug closes the gap
without polluting workflow surfaces.

**Done:**
- Migration 050 creates `device_renames` table
  (`client_id, client_name, platform, platform_device_id,
  old_norm_name, old_hostname, new_norm_name, new_hostname,
  detected_at, run_id`).
- `_detect_device_renames(run_id, source_run_ids)` runs at the end
  of `agent_compliance_ingest.run()` after observations are
  persisted. Single SQL: pick latest observation per
  `(client_id, platform, platform_device_id)` from this run's
  source_runs, LATERAL join the most recent prior observation for
  the same key, insert when `norm_name` differs.
- Detection is idempotent: once the rename row exists, the next
  collection's prior-observation lookup hits the new name and the
  comparison matches.
- Debug dashboard gets a `Recent device renames` card.

**Out of scope:** no findings, no alerts, no canonical alias merge.
If full historical-continuity-across-renames is needed later
(e.g., for SLA reporting), a separate canonical alias layer would
build on top of this signal.

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run.
- Migration 050 includes a one-time historical backfill (compare
  latest vs second-latest observation per
  `(client_id, platform, platform_device_id)`) so the All Data
  Health renames already in history register immediately. Expect
  ~10 rows for the `0115Y25 → ADH-RE03` batch plus anything similar
  in other customers' history.

## 2026-06-16 — v0.29.0 Broaden offline-platforms semantics

**Why:** Operator hit a device (`0115Y25`, customer All Data Health)
showing state `Missing` with both `Online in` and `Offline` columns
blank. Investigation showed Ninja+LogMeIn were required + present +
not currently online (last seen 14 days ago) but the 30-day
staleness threshold meant they didn't qualify as
`stale_required_platforms`. The `Offline` column on the work queue
is derived from `action_offline_platforms` which was scoped to stale
only — present-but-not-active platforms within threshold had no
visible home.

**Done:**
- Migration 049 rewrites `v_device_state_current` so
  `action_offline_platforms` = required + present + not currently
  online (regardless of stale threshold). Keeps the s1_exempt and
  source_failed exclusions.
- Same migration updates the `Missing` state_reason text to append
  `; offline in <platforms>` when other required platforms are
  present but offline. For 0115Y25 the Issue text now reads
  `Missing SentinelOne; offline in Ninja, LogMeIn`.
- Downstream views unchanged structurally (`v_device_work_queue`
  and `v_all_devices_human` still alias `offline_platforms AS
  stale_platforms`; the column shape stayed the same).
- Alert findings still come from Python `stale_required_platforms`
  (over-threshold), so alerting is unaffected by the broader view
  definition.

**Side effect (intentional):** devices with all required platforms
present but one or more not currently checking in will now classify
as `Offline` state rather than `Compliant`. Matches operator
intuition.

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run.
- Spot-check 0115Y25: should still show state `Missing`, but the
  `Offline` column now reads `Ninja, LogMeIn` and the Issue column
  surfaces both pieces of info.

## 2026-06-16 — v0.27.3 Drop v_notification_queue before recreate

**Why:** v0.27.2 fixed `v_active_findings` to expose `confirmed_gap`,
but the downstream `v_notification_queue` then failed on its
CREATE OR REPLACE with
`cannot change name of view column "rule_id" to "confirmed_gap"`.
Because `v_notification_queue` selects `a.*` from `v_active_findings`,
the new `a.*` is one column wider — shifting every named column
after it (rule_id, rule_key, etc.) right by one. CREATE OR REPLACE
cannot rename existing view columns, only append new ones at the
end.

**Done:**
- Added `DROP VIEW IF EXISTS ninja_agent_compliance.v_notification_queue`
  to migration 048 (right after the existing
  `v_notifications_ready` drop) so the next CREATE statement starts
  from a clean slate.

**Validation pending:**
- Portainer redeploy. Migration 048 should now apply on next start.

## 2026-06-16 — v0.27.2 Refresh v_active_findings to pick up confirmed_gap

**Why:** Migration 048 (v0.27.1) crash-looped the container with
`column f.confirmed_gap does not exist`. `v_active_findings` was
created in migration 035 with `SELECT f.*` from compliance_findings,
and PostgreSQL fixes a view's column list at CREATE time —
migration 045's `ALTER TABLE ... ADD COLUMN confirmed_gap` did not
flow into the existing view.

**Done:**
- Added a `CREATE OR REPLACE VIEW v_active_findings` step at the top
  of migration 048 (same SQL as 035 — `f.*` re-expands to include
  `confirmed_gap` at the end, which CREATE OR REPLACE permits).
- The rest of migration 048 (notification queue / readiness, customer
  alert setup, alert rules human view) now resolves `f.confirmed_gap`
  correctly.

**Validation pending:**
- Portainer redeploy. Migration 048 should now apply on the next
  startup; container should reach READY without the crash loop.

## 2026-06-16 — v0.27.1 Offline becomes alertable when confirmed

**Why:** Operator direction continuing from v0.27.0 — `Offline`
should be alertable when the device is still active/recent
somewhere else, while fully `Stale` devices stay out of alert
readiness. Metabase notification readiness was showing rows the
sender would never process; bring the view into reality.

**Done:**
- Migration 048 (`048_agent_compliance_offline_alerts.sql`):
  - `v_notification_queue` now filters `f.confirmed_gap` so Metabase
    shows exactly what `alerts.process_alerts` will process.
  - Human-facing wording renamed from `stale` to `offline` across
    notification-queue and rules views.
  - Added `v_customer_alert_setup` (includes the new `offline`
    alert row alongside the `missing_*` ones) and
    `v_alert_rules_human`.
- `ingest/agent_compliance/ingest.py`: `_findings_for_matrix` now
  sets `confirmed_gap = not matrix["is_stale"]` for
  `stale_required_platform`, so offline-but-recent devices become
  alertable and fully stale devices stay in the digest path. Summary
  text reads `is offline in required <platform>`.
- `ingest/main.py`: operator `set-customer-alert` endpoint adds an
  `offline` alert_key mapped to `stale_required_platform` (uses
  `stale` as the rule_key suffix so it shares storage with existing
  rules).
- `ingest/agent_compliance/metabase_bootstrap.py`: all four
  breakdown cards on Today and Devices restructured per the earlier
  directive — `Missing` / `Offline` / `Review` / `Total` are
  separate columns now instead of separate rows per state.
- `AGENT_COMPLIANCE_REBUILD_BLUEPRINT.md`: added explicit alert
  readiness rules (`Missing` alertable when confirmed; `Offline`
  alertable when device is still active/recent somewhere else;
  `Stale`/`Review`/ignored/excluded/cross-customer-ambiguous are
  not alertable; first-success only).

**Validation pending:**
- Portainer redeploy. Migration 047 (shipped in v0.27.0) plus 048
  should apply cleanly.
- After deploy: confirm Metabase notification readiness matches the
  set that the next evaluate-only run actually sends; spot-check a
  device with `Offline` state under the customer alert setup.

## 2026-06-16 — v0.27.0 Human device state model

**Why:** Operator-led rebuild of how Agent Compliance describes
device state. The earlier `Fix now / Review / Stale / Good`
breakdown mixed urgency with reason; the new model splits state
into operator-meaningful categories: `Compliant`, `Missing`,
`Offline`, `Stale`, `Review`, `Ignored`.

**Done:**
- Added `ninja_agent_compliance.v_device_state_current` as the
  authoritative reporting contract for device state, reason,
  recommended action, missing platforms, offline platforms, active
  platforms, and cross-customer review evidence.
- Added `ninja_agent_compliance.v_device_platform_detail_current`
  for the device drilldown — one row per platform rather than only
  the aggregate device row.
- Added the `human_decisions` table and the `Confirm missing`
  action path for cross-customer review cases.
- Added `Offline platform` as a Devices dashboard filter.
- Reworked active dashboard cards from `Fix now` wording to the new
  state model.
- Cross-customer same-name cases remain `Missing` but now carry
  review evidence and are no longer treated as fully confirmed
  unless an operator records a `Confirm missing` / `Not same
  device` decision.
- Missing-platform alerts no longer treat cross-customer ambiguity
  as confirmed without an operator decision.
- Migration 047 (`047_agent_compliance_device_state_model.sql`)
  carries the schema and view changes.

**Committed as:** `641cc48`.

## 2026-06-15 — v0.26.3 Compliant KPI query fix

**Why:** The Today `Compliant %` card used `is_compliant`, but
`v_all_devices_human` does not expose that column.

**Done:**
- Changed the KPI numerator to `state = 'Good' AND NOT ignored`.
- Kept the denominator as non-stale, non-ignored devices so stale
  devices do not pull down compliance.
- Added `Compliant devices` next to `Compliant %` in the first Today
  KPI row.

**Pending:**
- Bootstrap Metabase and confirm the card loads.

## 2026-06-15 — v0.26.2 Compliance KPI excludes stale devices

**Why:** The operator clarified that compliance means "for devices I
care about, does it have everything needed?" Stale devices are usually
offline/decommissioned candidates and should be counted separately
rather than pulling down compliance percentage.

**Done:**
- Changed Today `Compliant %` to calculate compliant non-stale,
  non-ignored devices divided by all non-stale, non-ignored devices.
- Added `Stale` to the first Today KPI row.
- Reflowed the top KPIs to: `Total devices`, `Compliant %`, `Fix now`,
  `Review`, `Stale`.

**Pending:**
- Bootstrap Metabase and visually confirm the first KPI row.
- Compare `Compliant %` against host SQL after deployment.

## 2026-06-15 — v0.26.1 Actionable cross-customer device rule

**Why:** The operator clarified that same-name cross-customer collisions
are expected MSP noise. They should only become device-level work when
the current customer is missing a required platform and that same
platform is visible under another customer with the same normalized
name.

**Done:**
- Updated the Device drilldown `Current device state` table to anchor
  the clicked row by normalized device identity, then show all current
  rows with that identity. This lets a cross-customer missing-platform
  case show both the selected customer and the customer where the
  missing platform was found.
- Reworked `sql/migrations/041_agent_compliance_demote_cross_client_conflicts.sql`
  so `v_device_work_queue` and `v_all_devices_human` compute an
  actionable cross-customer platform list and only show those cases in
  device-facing output.
- Left generic collision visibility for debug/customer summaries.
- Reworked the Agent Compliance Today top KPI strip so all seven
  required cards remain visible but no longer sit in one cramped row.
  The layout is now four cards on the first row and three on the
  second row.
- Shortened the two longest KPI labels: `First notifications ready`
  to `Ready to notify`, and `Collection problems` to
  `Collection issues`.
- Changed actionable cross-customer wording from same-name language to
  `found under another customer`, and grouped those rows in breakdowns
  as `Missing platform found elsewhere`.
- Appended the resumption note to `DEVELOPMENT.md` for future handoff.

**Pending:**
- Redeploy ingest so the new view definitions take effect.
- Confirm the device queue only surfaces cross-customer rows when a
  missing platform is present under another customer.
- Run the Metabase bootstrap and visually confirm the Today KPI row
  titles are no longer cut off.

## 2026-06-15 — v0.26.0 Review digest (Phase 2)

**Why:** Operator direction: confirmed gaps page (Phase 1), Review-
class items get one daily summary instead. This completes the alert
policy: Fix-now → first-success per-finding alerts, Review → daily
digest.

**Done:**
- Added `ingest.agent_compliance.review_digest.send_review_digest()`
  which loads active findings with `confirmed_gap = false` and finding
  type in `missing_required_platform` / `stale_required_platform`,
  composes a JSON payload (totals, by-customer, by-finding-type,
  sample items), and POSTs to the `review_digest` notification route.
- Cron scheduled in `main.py` (daily at
  `AGENT_COMPLIANCE_REVIEW_DIGEST_HOUR` UTC, default 08:00). Guarded
  by `AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED`.
- Manual trigger via `POST /run/agent-compliance-review-digest`.
- Migration 046 inserts the `review_digest` row in
  `notification_routes` (disabled by default; target_ref points at
  `AGENT_COMPLIANCE_REVIEW_DIGEST_WEBHOOK_URL`). Operator enables
  via Setup once the env var is set.
- Delivery recorded in `alert_events` with a synthetic finding
  signature `review_digest:YYYY-MM-DDTHH` so historical digests show
  up on the Alerts dashboard alongside per-finding events.

**Operator workflow to enable:**
1. Set `AGENT_COMPLIANCE_REVIEW_DIGEST_WEBHOOK_URL=...` and
   `AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED=true` in
   `/amr-ch-01_data/ninja-dashboard/.env`.
2. Redeploy.
3. Turn on the `review_digest` route in the Setup dashboard.
4. Test with `curl -X POST
   http://10.61.50.28:8090/run/agent-compliance-review-digest`.

## 2026-06-15 — v0.25.1 KPI split + breakdown reconciliation (Phase 3)

**Why:** The breakdown sums did not match the `Devices to fix` KPI
because the KPI included Review while breakdowns showed Fix now only,
and LIMIT 5 truncated the long tail. Now that alerts only fire on
Fix now (v0.25.0), the headline KPI should match what the breakdowns
group.

**Done:**
- Replaced the `Devices to fix` KPI with two scalars: `Fix now` and
  `Review`. The seven KPIs now sit in one row at 3-wide each.
- Dropped `LIMIT 5` from all four breakdown cards on Today and
  Devices. Cards scroll internally when the long tail is large;
  totals always reconcile to the Fix-now KPI.

**Next:**
- Phase 2 (Review digest): daily 08:00 cron that rolls Review-class
  findings into one notification via a `review_digest` route.

## 2026-06-15 — v0.25.0 Alerts gated to confirmed gaps only (Phase 1)

**Why:** Per operator direction — alerts should only fire on
confirmed gaps, not Review-state judgment calls. Review and Stale
work belongs in a separate digest (Phase 2). Stops paging on
"missing platform but device offline / agent degraded" cases.

**Done:**
- Migration 045 adds `confirmed_gap boolean NOT NULL DEFAULT false`
  to `compliance_findings` and an index on
  `(run_id, status, confirmed_gap)`.
- `_findings_for_matrix` now indexes observed platforms per
  (norm_name, client_id) once per evaluate, then sets `confirmed_gap`
  per finding:
    * `missing_required_platform`: true when the device has any
      online platform OR the missing platform is observed under the
      same normalized hostname for a different customer.
    * `stale_required_platform`: false (digest only).
- `_source_failure_findings`: `confirmed_gap = true` (operational).
- `alerts.process_alerts` SELECT adds `AND f.confirmed_gap`.

**Next:**
- Phase 3 (KPI split + breakdown reconciliation) so Today shows
  `Fix now` and `Review` as separate KPIs and breakdowns reconcile
  to the Fix-now total. Drop the LIMIT 5 truncation in favor of top
  5 + Other row.
- Phase 2 (review digest): daily 08:00 cron that summarizes current
  Review-class findings into one rolled-up notification.

**Validation pending:**
- Portainer redeploy + evaluate-only run, then:
  `docker exec -it ninja-postgres psql -U ninja -d ninja -c
   "SELECT finding_type, confirmed_gap, COUNT(*)
    FROM ninja_agent_compliance.compliance_findings
    WHERE status='active' GROUP BY 1,2 ORDER BY 1,2;"`
- Spot-check `v_notifications_ready` no longer shows offline / Review
  rows.

## 2026-06-15 — v0.24.1 OS family + device type — filter, column, breakdown

**Why:** Grouping Fix-now work by OS family (Windows 7/10/11/Server
2022/etc.) and by workstation vs. server lets operators target patch
cycles and platform-specific maintenance without scanning the queue.

**Done:**
- Migration 044 appends a derived `os_family` column to
  `v_device_work_queue` and `v_all_devices_human`. Buckets are driven
  by `ILIKE` against `os_name` against the actual values present in
  the deployed DB (Win 7/8/8.1/10/11, Srv 2008/2008 R2/2012/2012 R2/
  2016/2019/2022/2025, plus `Windows (other)`, `Windows Server
  (other)`, `Unknown`, `Other`).
- Added Devices dashboard params `OS family` and `Device type`. The
  Fix-now queue and All-devices table both pick them up.
- Added "OS / Type" column (abbreviated: `Win 11 · WS`, `Srv 2022 ·
  SRV`) to the Fix-now queue, All-devices table, and the Today Top
  device issues card.
- Added breakdown cards `Fix now by OS family` and `Fix now by device
  type` on both Today and Devices, giving a 2x2 grid (Customer / Issue
  type / OS family / Device type). Each card links to Devices with the
  matching filter + `state=Fix now` applied.

**Validation pending:**
- Portainer redeploy. Migration 044 should apply cleanly (column
  appended at the end of each view).
- Metabase bootstrap re-run, then visual check that the new column,
  params, and breakdown cards render and that clicking a breakdown
  row scopes the queue correctly.

## 2026-06-15 — v0.24.0 Fix now breakdown cards (Today + Devices)

**Why:** Operators wanted a fast read of where today's Fix now work
is concentrated — by customer (who needs my time) and by issue type
(systemic vs. one-off). The Fix now queue alone forced the operator
to scan rows to spot concentration.

**Done:**
- Added `Fix now by customer` and `Fix now by issue type` top-5 cards
  to both Today and Devices dashboards.
- On Today they sit between the KPI strip and `Top device issues`;
  each row links to Devices pre-filtered with `state=Fix now` plus the
  clicked customer.
- On Devices they sit in the previously empty gap at row 12 and act
  as in-page filter chips — clicking a row sets the same dashboard's
  customer / state filters. They respect the existing `Customer`
  filter so the breakdown narrows alongside the queue below.
- Issue-type buckets: `Cross-customer same name`, `Missing Ninja`,
  `Missing SentinelOne`, `Missing ScreenConnect`, `Missing LogMeIn`,
  `Agent degraded`, `Other`. Each Fix now device is bucketed in
  priority order so the totals add up to the Fix now count.

**Validation pending:**
- Portainer redeploy + Metabase bootstrap re-run, then visual check
  in the dashboard.

## 2026-06-15 — v0.23.9 Fix broken cross-customer migration

**Why:** Container was crash-looping on `am-ch-01` with
`column "cross_customer_actionable_platforms" does not exist` while
applying migration 041. v0.23.6 and v0.23.7 both put the new column as
a sibling alias in the same SELECT list and referenced it from another
CASE expression in the same SELECT — PostgreSQL does not allow that.
Neither 041 (my edit) nor 042 ever applied.

**Done:**
- Reverted migration 041 to the original demote-only definition shipped
  by v0.23.5 (1372a37). Codex's version applies cleanly.
- Rewrote migration 042 with a `with_actionable` CTE so the
  work-state CASE references the column from a parent CTE.
- Appended `cross_customer_actionable_platforms` at the END of both
  `v_device_work_queue` and `v_all_devices_human` SELECT lists, so
  `CREATE OR REPLACE` is column-compatible with what migration 040 /
  041 produced.

**Validation pending:**
- Portainer redeploy. Container should reach READY without migration
  errors.
- After deploy:
  `docker exec -it ninja-postgres psql -U postgres -d ninja -c
   "\d ninja_agent_compliance.v_device_work_queue" | tail -5`
  should show `cross_customer_actionable_platforms` as the last
  column.

## 2026-06-15 — v0.23.8 Stop emitting generic cross-customer findings

**Why:** v0.23.5/v0.23.6 removed generic cross-customer collisions from
the device work queue and promoted only the actionable subset. Full
review caught that the Python evaluator was still emitting a
`cross_client_conflict` finding (severity `high`) for every collision,
so the noisy `Device appears under more than one customer` text was
still leaking into `v_active_findings`, the Issues card, and the
notification queue. Operator confirmed seeing it.

**Done:**
- Removed the unconditional `cross_client_conflict` finding emission
  from `_findings_for_matrix` in `ingest/agent_compliance/ingest.py`.
- Added migration
  `043_agent_compliance_disable_cross_client_conflict_rule.sql` that
  disables the `alert_rules` row for `cross_client_conflict` so a
  route accidentally enabled on it cannot fire.

**Debug surface preserved:**
- `compliance_matrix_current.cross_client_conflict` boolean stays.
- `v_cross_client_conflicts` view stays.
- Customer / debug Metabase cards that surface raw name collisions
  stay.
- Metabase CASE branches that label historical
  `cross_client_conflict` alert events stay so the alert-history table
  still renders a human label.

**Validation pending:**
- Portainer redeploy then on `am-ch-01`:
  `docker exec -it ninja-postgres psql -U postgres -d ninja -c
   "SELECT COUNT(*) FROM ninja_agent_compliance.compliance_findings
    WHERE finding_type='cross_client_conflict' AND status='active';"`
  should drop to 0 after the next collection or evaluate run.
- Issues / Notifications cards in Metabase no longer show
  `Device appears under multiple customers` rows.

## 2026-06-15 — v0.23.7 Fix wording regression + dead-code cleanup

**Why:** Code review of the codex commits from earlier today found:
1. Migration 041 (v0.23.5) rebuilt `v_device_work_queue` and
   `v_all_devices_human` from an older copy and reintroduced
   `seen online in`, undoing the wording fix shipped by migration 040
   (v0.23.2).
2. The first-success alert refactor (v0.23.1) left
   `AGENT_COMPLIANCE_ALERT_COOLDOWN_HOURS` and the `_get_state` helper
   behind with no remaining readers.

**Done:**
- Added migration
  `042_agent_compliance_restore_online_in_wording.sql` that
  `CREATE OR REPLACE`s both views with the corrected literals:
  `online in` and `same name under another customer`.
- Removed `AGENT_COMPLIANCE_ALERT_COOLDOWN_HOURS` from
  `ingest/config.py` and `.env.example`.
- Removed the orphan `_get_state` function from
  `ingest/agent_compliance/alerts.py`.

**Validation pending:**
- Portainer redeploy then verify on `am-ch-01`:
  `SELECT DISTINCT issue FROM ninja_agent_compliance.v_device_work_queue
   WHERE issue LIKE '%online in%' OR issue LIKE '%under another customer%';`
  should show only `online in` (no `seen online in`) and
  `same name under another customer` (no `seen`).

## 2026-06-15 — v0.23.6 Promote actionable cross-customer cases

**Why:** v0.23.5 removed all cross-customer name collisions from the
device work queue, but the operationally important case — same device
name missing a required platform under customer A while that platform
is observed under customer B — should remain a `Fix now` item. The
generic same-name-across-customers noise stays demoted.

**Done:**
- Refined migration
  `041_agent_compliance_demote_cross_client_conflicts.sql` to add a
  `cross_customer_actionable_platforms` array on the device work queue
  and the all-devices human view.
- Devices with one or more actionable cross-customer platforms are
  classified as `Fix now` with issue text
  `Missing <platforms>; same name seen under another customer`.
- Non-actionable cross-customer collisions stay out of the device
  queue and remain visible in the customer/debug summary.

**Validation pending:**
- Portainer redeploy + `\d ninja_agent_compliance.v_device_work_queue`
  on `am-ch-01` to confirm the new column, and a spot check that
  representative devices show as `Fix now` with the new issue text.

## 2026-06-15 — v0.23.5 Demote cross-customer collisions

**Why:** Same names across customers are expected MSP data. They should
not appear like a device fix item in the primary workflow.

**Done:**
- Removed cross-customer collisions from the device work queue.
- Removed the collision state from the all-devices human view.
- Kept the collision summary on the customer/debug side with platform
  detail.

## 2026-06-15 — v0.23.4 Cross-customer platform detail

**Why:** Same names across customers are common MSP data. The conflict
card needed to show the involved customers and platforms without making
the operator hunt through drilldowns.

**Done:**
- Renamed the card to `Same name across customers`.
- Added `Platforms seen` to the conflict summary.
- Kept the actionable `Fix now` logic separate from cross-customer
  collisions.

## 2026-06-15 — v0.23.3 Cross-customer conflict drilldown

**Why:** Cross-customer conflicts were visible, but the operator did not
have a single place to see the device plus the involved customers and
platforms, and the drilldown required customer context even when the
conflict itself was enough to identify the device.

**Done:**
- Rolled the cross-customer conflict cards up to one row per device.
- Added the customer list and online-platform list directly to the
  conflict table.
- Made the device drilldown host-first so it can open from a conflict
  row without requiring a customer value.

## 2026-06-15 — v0.23.2 Agent Compliance wording cleanup

**Why:** The phrase `Seen online in` was unnecessarily wordy for the
device workflow. The table already communicates platform presence, so
`Online in` is clearer.

**Done:**
- Renamed dashboard columns and filters from `Seen online in` to
  `Online in`.
- Renamed `Missing but seen online somewhere else` to
  `Missing but online somewhere else`.
- Added migration `040_agent_compliance_online_in_wording.sql` so the
  generated issue text says `online in`, not `seen online in`.

## 2026-06-15 — v0.23.1 First-success alert dispatch

**Why:** Alerting should not be a timer that repeatedly scans unchanged
issues. Issues are found through collection plus evaluation, so alerting
should run after evaluation and only notify once for a given issue.

**Done:**
- Changed Agent Compliance alert delivery to first-success only.
- Failed deliveries can retry on later evaluations until one delivery
  succeeds.
- Scheduled evaluate-only refresh now runs every 30 minutes by default
  with `AGENT_COMPLIANCE_EVALUATE_SCHEDULE_MINUTES`.
- Config-triggered and manual evaluate-only refreshes dispatch alerts
  after rebuilding current findings.
- Added an Agent Compliance lock so full collection and evaluate-only
  refreshes do not overlap matrix writes.
- Added migration `039_agent_compliance_first_time_alerts.sql` to align
  notification queue views with first-success alerting.
- Updated dashboard wording from generic/repeat semantics to first
  notification semantics.

## 2026-06-15 — v0.23.0 Agent Compliance evaluate-only refresh

**Why:** Required-platform and alias changes should not wait for the
next multi-hour vendor collection cycle. Ingest should collect facts;
the compliance model should be able to re-evaluate those facts whenever
configuration changes.

**Done:**
- Added an evaluate-only Agent Compliance path that rebuilds the current
  compliance matrix and findings from the latest successful stored
  observations per source.
- Evaluate-only re-resolves stored observations against current customer
  and alias config before writing the matrix, so alias/customer changes
  take effect without a full vendor pull.
- Added `POST /run/agent-compliance-evaluate`.
- Customer, alias, requirement, exclusion, stale-threshold, and
  device-ignore actions now schedule an evaluate-only refresh.
- Device ignore defaults changed from 90 days to 30 days, with a small
  duration form when clicking `Ignore`.
- Cleaned primary table ergonomics: fixed important column widths and
  removed the low-value route column from `Open issues not notifying`.

## 2026-06-15 — v0.22.2 Today actionable device count

**Why:** `Devices to fix` on Today still included stale-only devices,
which made the landing-page number too large and less actionable. Stale
devices are maintenance work, not the same as an online device missing a
required platform.

**Done:**
- Today `Devices to fix` now counts only `Fix now` and `Review`.
- Today `Top device issues` uses the same active-work filter.
- Stale-only devices remain visible on Devices under stale maintenance.
- Added migration `038_agent_compliance_simplify_device_states.sql`.
- Simplified workflow states to `Fix now`, `Review`, `Stale`,
  `Ignored`, and `Good`.
- Degraded agents, cross-customer conflicts, and unknown states are now
  issue details under `Review`, not separate state/filter values.

## 2026-06-15 — v0.22.1 Today card order

**Why:** The Today top row should start with total inventory context,
then compliance and action counts. `Ignored devices` is useful but not
important enough for the landing-page KPI row.

**Done:**
- Added `Total devices` as the first Today KPI.
- Reordered Today KPIs:
  `Total devices`, `Compliant %`, `Devices to fix`,
  `Notifications ready`, `Names to review`, `Collection problems`.
- Removed `Ignored devices` from the Today top row. It remains visible
  on Devices under ignored/restorable devices.

## 2026-06-14 — v0.22.0 Agent Compliance Level 1 operations rebuild

**Why:** The dashboard was technically improving but still mixed daily
device work, alert configuration, customer-name cleanup, and raw system
plumbing. A human operator or admin could not quickly tell what needed
action, what would notify someone, or why an issue was not notifying.

**Done:**
- Added migration `037_agent_compliance_level1_queues.sql` with
  purpose-built human queues:
  - `v_device_work_queue`
  - `v_all_devices_human`
  - `v_device_gap_summary`
  - `v_notification_queue`
  - `v_notifications_ready`
  - `v_customer_name_queue`
  - `v_required_platforms_effective`
  - `v_customer_alert_setup`
  - `v_alert_rules_human`
  - `v_notification_routes_human`
  - `v_system_health_queue`
- Added `Agent Compliance - Setup` to the top nav.
- Rebuilt the active dashboard spec around:
  `Today | Devices | Alerts | Customers | Setup | Health | Debug`.
- Moved alert rules, customer alert setup, required platforms,
  notification routes, and source setup to `Setup`.
- Reworked `Alerts` so it shows notification operations first:
  `Notifications ready to send`, `Open issues not notifying`,
  `Recently notified`, and `Open device issues`.
- Reworked `Devices` to use the device work queue, hide source-failed
  false gaps from device work, honor S1 `NO AV` exemptions, and keep the
  full manual-filter device table at the bottom.
- Reworked `Customers` to focus on customer names and aliases only.
- Reworked `Health` to focus on data confidence: collection/delivery
  problems, source health, current gaps, and name-review volume.
- Device ignore and bulk stale-ignore actions now default to 90-day
  expiring suppressions while staying reversible.

**Intentional boundary:**
- This is Level 1 only. It does not rebuild device identity or create a
  canonical device-linking layer across Ninja/S1/LMI/ScreenConnect IDs.

## 2026-06-14 — v0.21.10 Current findings cleanup

**Why:** The Today dashboard showed 29k+ active alerts/findings. That
was not actionable. Root cause: `compliance_findings` was append-only
per run while old rows stayed `active`, so dashboard counts accumulated
historical duplicate rows.

**Done:**
- Added migration `035_current_active_findings.sql` to redefine
  `v_active_findings` as the latest active row per finding signature,
  with suppressions applied.
- Added migration `036_cleanup_duplicate_findings.sql` to delete old
  unreferenced duplicate finding rows while preserving rows referenced
  by alert delivery history.
- Updated ingestion so each new findings write resolves the previous
  active snapshot before inserting the new current snapshot.
- Renamed the Today KPI from `Active alerts` to `Current findings`.
- Changed `Would fire on next run` to read from the deduped current
  findings view.

**Alert behavior:**
- Alert state is not reset by this cleanup, so existing alert cooldown
  state should prevent mass re-fire.
- If a finding never had `alert_state`, it may still alert as new if it
  is eligible under an enabled alert rule.

## 2026-06-13 — v0.21.9 Per-platform requirement toggles

**Why:** Required coverage was shown as a few preset combinations. That
made one-off platform changes hard to understand and harder to audit.

**Done:**
- `Required coverage` now shows one column per platform:
  `Ninja`, `SentinelOne`, `LogMeIn`, `ScreenConnect`.
- Each platform cell shows `On` or `Off` and flips only that platform.
- Added `/a/tp` to toggle a single platform for a customer/scope.
- If the customer/scope has no exact override, the action copies the
  effective requirement first, then applies the single-platform flip.
- Existing preset endpoint `/a/sr` remains for compatibility but is no
  longer shown in the dashboard.

## 2026-06-13 — v0.21.8 Customer review actions

**Why:** The separate alias card added in v0.21.7 did not match the
operator workflow. Customer-name review needs the decision directly on
the review row: add, alias, or ignore.

**Done:**
- Removed the separate `Alias customer name` dashboard card.
- `Customer names to review` now shows:
  - `This is a customer`
  - `Alias suggestion` when a suggestion exists
  - `Manual alias`
  - `Ignore name`
- `Manual alias` opens a small controlled picker page where the
  operator selects the existing customer target.
- Removed low-value `Source` columns from the customer-name dashboard
  tables.

**Design note:**
- Metabase cannot safely pass an arbitrary dashboard dropdown value
  into a row action URL without either duplicate rows or brittle SQL.
  The manual alias picker keeps the main dashboard clean while still
  allowing any target customer to be chosen.

## 2026-06-12 — v0.21.7 Customer-name alias review

**Why:** `Customer names to review` only offered `Approve` or
`Ignore`, but the common PowerShell workflow is often a third option:
this name belongs to an existing customer.

**Done:**
- Added suggested-customer visibility to `Customer names to review`.
- Added `Alias customer name`, a manual alias workflow that lets the
  operator choose any existing customer as the target. Suggestions are
  listed first, but selecting the `Alias target` dashboard filter
  allows an explicit manual choice even when no suggestion exists.
- Updated alias promotion so it works for any enabled customer, not
  only customers currently represented in `org_alignment_current`.

**Operator flow:**
- If the name is a real new customer: click `This is a customer`.
- If the name is noise: click `Ignore name`.
- If the name belongs to an existing customer: filter/select the target
  in `Alias customer name` and click `Alias`.

## 2026-06-12 — v0.21.6 Alert rule controls

**Why:** The Alerts dashboard showed generic internal finding names
and did not expose alert-rule state clearly. Operator asked whether
alerts could be platform-specific, visible in the dashboard, toggled
per rule, and enabled per customer.

**Done:**
- Alert rows now display human labels such as `SentinelOne missing`
  and `LogMeIn stale`; the underlying finding type remains unchanged.
- Added an Alerts dashboard `Alert rules` card showing global/customer
  scope, severity, route, route state, cooldown, and rule state.
- Added action links to turn individual alert rules on/off through
  `/a/tr`.
- Added `Customer alert setup` with `/a/sca` action links to create or
  update customer-scoped alert rules. This supports controlled opt-in:
  global device rules off, selected customers on per alert type.
- Added migration `034_customer_opt_in_device_alerts.sql` to turn off
  global device-alert rules (`missing_required_platform`,
  `stale_required_platform`, and `cross_client_conflict`) while leaving
  source/system alerts untouched.
- Updated Health `Missing by platform` to exclude ignored devices,
  excluded customer names, and S1 `NO AV` exemptions.
- Added `All current devices` at the bottom of Devices as the
  manual-filter escape hatch. Metabase dashboard cards cannot be
  reliably set to collapsed-by-default through the API, so this is
  placed last under `Full device list`.

**Behavior notes:**
- Missing-platform findings are already one finding per affected
  platform; the UI now reflects that explicitly.
- Stale platform findings are alertable through the
  `stale_required_platform` rule.
- Ignored devices suppress active findings and alert delivery via
  `alert_suppressions`.
- Excluded customer names are filtered before they become managed
  customer/device work.
- Customer alert control is opt-in via customer-scoped alert rules, not
  suppressions. If a global device rule is manually turned back on, it
  can still alert for all matching customers.

## 2026-06-12 — v0.21.0 Clean reset migration

**Why:** The previous session's audit revealed that dynamic discovery
(pre-v0.16.4) had created duplicate canonical clients (GGI vs
GGI International, BH vs BH Management, City Painting (CPS) vs CPS,
Trimworx-Deco-BGG vs Deco/Trimworx) and demoted legitimate ones
(Bobov45 with 1094 Ninja devices). The matrix also carried stale
observations and exempt flags from before the v0.19.0 NO AV fix.
Operator decision: wipe runtime state + dynamic cruft, keep the
PowerShell-derived seed, let discovery rebuild from scratch.

**Done:**
- Migration `030_clean_reset.sql` TRUNCATEs all compliance state
  (matrix current/history, findings, alert state/events, alignment
  history, observations, source runs, org candidates) and DELETEs
  dynamic-discovery rows from `client_aliases`, `platform_requirements`,
  `clients`, and per-client `platform_sources`.
- Migration `031_clean_reset_by_name.sql` follows up with explicit
  name-list cleanup for ghost-seeded clients that inherited the
  default `source='seed'` before v0.16.4. After live FK failures,
  `031` was corrected to re-truncate runtime state first, then delete
  the ghost-seeded aliases, requirements, sources, suppressions, and
  clients.
- Migration `032_retry_clean_reset_by_name.sql` exists because the
  host may already have `031` marked applied. It repeats the corrected
  cleanup idempotently and tolerates partial manual SQL cleanup.
- The PS seed (source='seed') and any operator-manual rows
  (source='manual') from migrations 019/021/029 stay.
- Shared `platform_sources`, `notification_routes`, `alert_rules`,
  and `alert_suppressions` for PS-seeded clients are preserved.

**Scope discipline:**
- No promote/demote of clients outside the PS seed — operator
  handles those manually via the Customers review queue after first
  discovery cycle.
- No name changes (typos like Park Bookeeping stay; LMI/S1
  variants are already aliased to it).
- No proactive `org_excludes` additions (Unknown / Various /
  Default site stay in the review queue, operator decides per row).

**Expected outcome after deploy:**
- Bobov45, Glas, D Miller Books, etc. resurface in
  `Customer names to review`.
- The duplicate-canonical collisions resolve (only PS-seeded sides
  remain; PS aliases route observations correctly).
- Compliance matrix rebuilds clean with the v0.19/v0.20 NO AV +
  AgentDevice fixes applied from the start.

**Pending follow-ups:**
- First end-to-end webhook delivery (still waiting on a sink URL).
- After first post-reset run, snapshot the review queue and audit
  whether discovery picked up everything the operator expects.

## 2026-06-12 — v0.21.3 Ninja-authoritative customer discovery

**Why:** After the clean reset, the system correctly preserved only
the 27 PowerShell-seeded customers, but every non-seeded Ninja org
landed in review. Operator decision: Ninja is authoritative for
customer names. If a name exists in Ninja, it should become a customer
automatically. Non-Ninja names should only auto-alias when they match
that customer exactly after normalization; fuzzy/prefix cases stay in
review.

**Done:**
- `sync_clients_from_observations` now auto-creates enabled clients
  with `source='ninja'` when the name is observed in Ninja and is not
  excluded/placeholder noise.
- Auto-created customers include notes documenting the data source and
  logic that made them customers.
- Ninja aliases for those customers use `source='ninja'`; exact
  normalized S1/LMI aliases use the existing alignment alias path.
- Removed the conservative fuzzy/prefix auto-alias behavior from the
  discovery step so ambiguous names remain operator review work.

## 2026-06-12 — v0.21.4 Review queue cleanup

**Why:** After Ninja-authoritative discovery, Today still showed Ninja
rows in `New customer names found` / `Customer names to review`.
Those were stale open `org_candidates` rows from before the customer
was accepted, not real unresolved customer names.

**Done:**
- Auto-accepted Ninja customer names now close matching open
  `org_candidates` rows in the same run.
- Migration `033_filter_accepted_org_candidates.sql` closes existing
  stale candidates and changes `v_org_candidates_current` to hide any
  candidate already accepted by customer name or alias.

## 2026-06-12 — v0.21.5 Devices Need action SQL fix

**Why:** The `Need action` card on Devices threw
`ERROR: syntax error at or near "]"`. The likely cause was Metabase
rendering the multi-select array-overlap clauses around
`ARRAY[{{missing}}]` / `ARRAY[{{online_in}}]` into invalid SQL.

**Done:**
- Rewrote those two filters as `EXISTS ... IN ({{filter}})` clauses.
  This preserves the dashboard filters without using array-literal
  syntax around Metabase variables.

## 2026-06-12 — v0.20.0 Alerts surface

**Why:** With routes still off, there was no way to see what *would*
fire if alerts were enabled. The `would-fire` SQL preview from the
previous session made the data accessible via psql but didn't surface
on the dashboard.

**Done:**
- Added an `Active alerts` KPI on Today (click-through to the new
  Alerts dashboard).
- Built `Agent Compliance — Alerts` in the top nav with three
  sections (Would fire / Active findings / Recent deliveries) and
  Customer / Severity / Finding type filters using the same
  parameter infrastructure introduced in v0.18.0–v0.19.0.
- The `Would fire on next run` table mirrors `alerts.py:_event_type`
  semantics so the operator can pre-validate dispatcher behavior
  before flipping `AGENT_COMPLIANCE_ALERTS_ENABLED` on.

**Validation:**
- `python -m compileall ingest/agent_compliance/metabase_bootstrap.py`
  passes.
- Live host run pending: redeploy ingest, `POST /bootstrap-metabase`,
  confirm Alerts is in the nav, filters render, "Would fire" returns
  rows for active findings whose route would be enabled.

**Pending follow-ups:**
- Wire the first webhook URL → flip the seed `default_webhook` route
  enabled, set `AGENT_COMPLIANCE_ALERT_WEBHOOK_URL` + flip
  `AGENT_COMPLIANCE_ALERTS_ENABLED=true`, trigger
  `/run/agent-compliance`, watch `Recent deliveries` populate.
- Reset migration (clean-slate request from previous session) still
  pending the three yes/no decisions on Star Funding canonical,
  re-promote list, and additional `org_excludes`.

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
