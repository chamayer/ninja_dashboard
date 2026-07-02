# Goal

Redesign the patching dashboards around fast, human-first patch
operations reporting while preserving click-through filtering.

# Why

Current patching dashboards contain most of the needed signals, but the
story is fragmented. Org Overview and other cards often present counts
without making it obvious whether patching is running, what needs work,
or why devices/clients are blocked.

# Scope

- Reframe patching around functional areas, not formal roles:
  - Command Center: cross-client patch status and exceptions.
  - Client Patch Status: one-client patch report.
  - Triage: device/action queue and failure investigation.
  - Device Drilldown: full single-device evidence.
  - Trends / Reporting: time-series and exportable evidence.
- Keep Metabase as the reporting UI with limited feedback/actions.
- Preserve and expand useful click-through filter behavior.
- Make page load speed a hard requirement.
- Design for an internal AMR operator wearing multiple hats in a small
  MSP; client-facing output is reporting/export evidence, not the
  operational landing view.

# Out of scope

- No custom web app yet.
- No broad workflow system with ownership, assignment, or ticket state.
- No change to ingest cadence unless dashboard evidence proves it is
  needed.
- No removal of existing supporting dashboards until replacements prove
  equivalent.

# Files to change

- `ingest/metabase_bootstrap.py`
  - Dashboard layout, filters, card SQL, click-through mappings.
- Conditional: `sql/migrations/065_patch_operations_current.sql` or
  similar
  - Add canonical current reporting views/materialized views if the
    baseline shows landing dashboards or repeated logic need them.
- Conditional: `ingest/summary_views.py` or patch ingest refresh path
  - Refresh new materialized views after patch/activity/core ingest if
    new MVs are added.
- `CHANGELOG.md`
  - Record the dashboard redesign.
- `SESSIONS.md`
  - Record decisions and validation notes.
- `TODO.md`
  - Move superseded dashboard follow-ups or add deferred polish.
- `VERSION`
  - Bump version when implementation ships.

# Design rules

- Page load must be quick:
  - Command Center and Client Patch Status should load under 4 seconds on a
    broad/cold open and under 3 seconds p95 in normal filtered use.
  - Individual card queries target under 1 second; anything over 2
    seconds needs a fix or explicit justification.
  - Canonical views/materialized views are presumed in-scope for
    landing views unless the baseline proves direct card SQL already
    meets target.
  - Keep broad tables capped and show total matching row count in a
    separate scalar when needed.
  - Avoid `COUNT(*) OVER()` on large limited tables.
  - Add indexes with any new reporting view that filters by client,
    device, policy, scope, issue, scan time, install time, or activity
    time.
- Human consumer first:
  - Show work/status language, not database terms.
  - Put decision columns before verbose evidence.
  - Keep full raw/debug detail out of landing sections.
  - Show full error text only where failure investigation needs it.
- Click-throughs are part of the product:
  - Client row/cell opens Client Patch Status with client filter.
  - Bad client/device category opens Triage with matching filters.
  - Device opens Device Drilldown.
  - KB opens Patch Detail.
  - Error category opens Triage/failure section filtered to that error.
  - OS, policy, scope, and issue fields self-filter where useful.
  - Use stable lowercase SQL aliases for click-source columns.

# Locked decisions

- Preserve existing Metabase dashboard identities/IDs where practical;
  update visible/nav labels to functional names.
- `Org Overview` is renamed in place to Client Patch Status with legacy
  dashboard/card identity handling so existing dashboards are updated,
  not duplicated.
- Recent windows are dashboard parameters, defaulting to 30 days, not
  hardcoded constants.
- Replacement proves equivalent through an old-to-new functional mapping,
  not equal card count. Do not remove or hide old cards/dashboards until
  their operational answers and click-through paths have accepted new
  homes.
- Triage owns detailed Approval Backlog and Reboot Completion queues.
  Client Patch Status may show client-scoped summary counts/top blockers;
  Command Center may show cross-client summaries/ranking.

# Client patch status model

Use a rule-stack status model for v1, not a weighted black-box score.
Statuses must be explainable directly in the UI with `Reason`.

- `Data Stale`
  - the dashboard data itself is too old or missing, so other patch
    conclusions should not be trusted yet.
- `Needs Action`
  - no recent successful scan on included devices;
  - active patch failures;
  - stalled/never-patched included devices;
  - reboot blockers;
  - manual approval backlog.
- `Watch`
  - warnings;
  - delayed backlog;
  - low recent-install activity;
  - no included patching devices.
- `Good`
  - included devices are scanning and patching recently;
  - no material blockers.

Within each status, sort by status severity first, then affected device
count, oldest blocker age, and client name.

# Triage ordering

Triage queue priority order:

1. Data confidence blockers.
2. No successful scan on included devices.
3. Active operational failures.
4. Failed installs.
5. Stalled / never-patched included devices.
6. Reboot blockers.
7. Manual approvals.
8. Warnings / watch items.

Each row should expose priority, client, device, problem, likely
cause, next step, last scan, last install attempt, last contact, and a
click path to Ninja and Device Drilldown.

# Target dashboards

1. Command Center
   - Cross-client patch status ranking.
   - Management summary band: good/watch/needs-action/data-stale
     clients, data-confidence problems, clients needing follow-up.
   - Patch progress pulse.
   - Data confidence / ingest freshness.
   - Top exceptions by client and issue.
   - Fast click-through into Client Patch Status or Triage.

2. Client Patch Status
   - Current Org Overview reshaped and renamed as a one-client report.
   - Patching enabled/included devices.
   - Successful scan coverage and no-scan devices.
   - Recently installed devices.
   - Stalled / never-patched devices.
   - Failures, warnings, reboot blockers, manual approvals.
   - Top devices needing attention.
   - Export-friendly evidence tables: installed recently, unresolved
     blockers, exclusions, failures/warnings, reboot blockers.

3. Triage
   - Main device work queue.
   - Scope / eligibility issues.
   - Scan confidence issues.
   - Failed installs and operational failures.
   - Reboot completion blockers.
   - Approval backlog.
   - Search filters for device, KB, and error/message text.
   - Full error message available in failure investigation tables.
   - Blocker ownership/type: data confidence, MSP action, client/user
     action, policy/expected, offline/unreachable.

4. Device Drilldown
   - Full single-device context.
   - Action summary at top: current problem, likely cause, suggested
     next step, last scan, last install, last failure.
   - Scope, policy, last contact, last scan, last install.
   - Current patch state and install history.
   - Warning/failure history with full or sufficiently long messages.
   - Open in Ninja link.

5. Trends / Reporting
   - Installs over time.
   - Failed installs over time.
   - Operational failures and warnings over time.
   - Active/stalled/never-patched movement.
   - Client/exportable evidence.

Supporting dashboards:
- Patch Detail remains the KB/current-state drill-through page.
- Utilities remains broad activity search, but important search paths
  should be reachable from Triage.

# Functional coverage

- Client Patch Status
- Device Triage
- Failure Investigation
- Patch Progress
- Scan / Inventory Confidence
- Scope / Eligibility
- Approval Backlog
- Reboot Completion
- Remediation Follow-Up
- Reporting / Evidence

# Acceptance checks

- Command Center ranks clients by the documented status rules and shows
  the reason behind each status.
- Client Patch Status answers the same patch status questions for one client as
  an export-friendly report.
- Triage uses the documented priority order and exposes enough evidence
  for a junior tech to know what to check next.
- Device Drilldown shows full scope, scan, install, warning/failure,
  reboot, next-step, and Ninja-link evidence for the selected device.
- Trends shows patch progress and failure movement over the selected
  window.
- A real operator walkthrough can answer: which clients need action,
  which devices need work, what is blocking them, and where is the full
  evidence, without schema explanation.

# Steps

1. Lock dashboard naming/identity strategy, deployment/bootstrap behavior,
   old-to-new functional mapping, and speed baseline:
   - current dashboard/card query timing;
   - dashboard broad vs filtered load behavior;
   - existing click-through paths to preserve;
   - current bootstrap trigger after Portainer deploy;
   - concrete status thresholds;
   - concrete within-status client ordering.
2. Audit current card SQL and identify reusable canonical result shapes:
   client patch status, device triage, scan confidence, failure events.
3. Decide which shapes need materialized views for speed.
4. Add migration/view refresh plumbing if needed.
5. Rework Command Center into cross-client patch status and exceptions.
6. Rework Org Overview into Client Patch Status while preserving existing
   click-through behavior.
7. Rework Issues/Device Patching Status into a sharper Triage workflow.
8. Tighten Device Drilldown failure/warning detail and Ninja links.
9. Adjust Trends only where reporting gaps remain.
10. Run compile checks and dashboard spec build checks.
11. Bootstrap Metabase on the stack and validate:
    - page load speed;
    - dashboard filters;
    - click-through parameter propagation;
    - capped table counts;
    - full error/message visibility where intended;
    - human-consumer walkthrough.

# Status

Blueprint implemented locally:
- visible and stored dashboard names now use Client Patch Status, Triage,
  and Patch Trends, with legacy dashboard/card matching for existing
  Metabase installs;
- Command Center ranks clients by explicit status rules and shows the
  reason behind each status;
- Client Patch Status answers enabled, scanned, installed recently, needs
  action, failures, reboot blockers, approval backlog, and stalled-device
  questions;
- Triage includes priority, blocker, full messages, message-text search,
  scan gaps, reboot blockers, approval backlog, and stalled/never-patched
  subqueues;
- Device Drilldown surfaces current problem, suggested action, install
  attempt/failure timing, and full warning/failure messages;
- click-through aliases were preserved on client, device, patch state,
  KB, and device type columns.

Live validation completed:
- Metabase bootstrap/deploy applied Command Center and Client Patch
  Status naming/filter changes;
- Command Center page shell/API and all card runtimes meet the
  documented target;
- live click-through mappings are present for Command Center, Client
  Patch Status, and Triage key cards;
- Triage message search works on the main queue and warning/error
  category detail cards;
- Client Patch Status and Triage full card sweeps meet the documented
  per-card target after v0.34.6.

Status: done — committed through 8c8c791, with live card SQL updated to
the v0.34.6 definitions and validated against Metabase.
