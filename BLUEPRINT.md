# Goal

Redesign the patching dashboards around fast, human-first patch
operations reporting while preserving click-through filtering.

# Why

Current patching dashboards contain most of the needed signals, but the
story is fragmented. Org Overview and other cards often present counts
without making it obvious whether patching is healthy, what needs work,
or why devices/customers are blocked.

# Scope

- Reframe patching around functional areas, not formal roles:
  - Command Center: cross-customer health and exceptions.
  - Customer Health: one-customer health report.
  - Triage: device/action queue and failure investigation.
  - Device Drilldown: full single-device evidence.
  - Trends / Reporting: time-series and exportable evidence.
- Keep Metabase as the reporting UI with limited feedback/actions.
- Preserve and expand useful click-through filter behavior.
- Make page load speed a hard requirement.
- Design for an internal AMR operator wearing multiple hats in a small
  MSP; customer-facing output is reporting/export evidence, not the
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
  - Command Center and Customer Health should load under 4 seconds on a
    broad/cold open and under 3 seconds p95 in normal filtered use.
  - Individual card queries target under 1 second; anything over 2
    seconds needs a fix or explicit justification.
  - Canonical views/materialized views are presumed in-scope for
    landing views unless the baseline proves direct card SQL already
    meets target.
  - Keep broad tables capped and show total matching row count in a
    separate scalar when needed.
  - Avoid `COUNT(*) OVER()` on large limited tables.
  - Add indexes with any new reporting view that filters by customer,
    device, policy, scope, issue, scan time, install time, or activity
    time.
- Human consumer first:
  - Show work/health language, not database terms.
  - Put decision columns before verbose evidence.
  - Keep full raw/debug detail out of landing sections.
  - Show full error text only where failure investigation needs it.
- Click-throughs are part of the product:
  - Customer row/cell opens Customer Health with organization filter.
  - Bad customer/device category opens Triage with matching filters.
  - Device opens Device Drilldown.
  - KB opens Patch Detail.
  - Error category opens Triage/failure section filtered to that error.
  - OS, policy, scope, and issue fields self-filter where useful.
  - Use stable lowercase SQL aliases for click-source columns.

# Locked decisions

- Preserve existing Metabase dashboard identities/IDs where practical;
  update visible/nav labels to functional names.
- `Org Overview` becomes visible as Customer Health if feasible without
  breaking compatibility; otherwise the nav label says Customer Health
  while the stored dashboard name remains stable.
- Recent windows are dashboard parameters, defaulting to 30 days, not
  hardcoded constants.
- Replacement proves equivalent through an old-to-new functional mapping,
  not equal card count. Do not remove or hide old cards/dashboards until
  their operational answers and click-through paths have accepted new
  homes.
- Triage owns detailed Approval Backlog and Reboot Completion queues.
  Customer Health may show customer-scoped summary counts/top blockers;
  Command Center may show cross-customer summaries/ranking.

# Customer health model

Use a rule-stack/tier model for v1, not a weighted black-box score.
Tiers must be explainable directly in the UI with `health_reason`.

- `Broken`
  - stale dashboard data;
  - no scan coverage on included devices;
  - active failures above the Step 1 threshold.
- `At Risk`
  - stalled/never-patched included devices above threshold;
  - reboot blockers above threshold;
  - manual approval backlog above threshold.
- `Watch`
  - warnings above threshold;
  - delayed backlog above threshold;
  - low recent-install activity below threshold.
- `Healthy`
  - enabled/included devices are scanning and patching recently;
  - no material blockers.

Step 1 must pin concrete thresholds for each placeholder above before
Command Center is implemented. Within each tier, sort by severity inputs
first, then affected device count, oldest blocker age, and customer name.

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

Each row should expose priority, customer, device, problem, likely
cause, next step, last scan, last install attempt, last contact, and a
click path to Ninja and Device Drilldown.

# Target dashboards

1. Command Center
   - Cross-customer health ranking.
   - Management summary band: healthy/watch/at-risk/broken customers,
     data-confidence problems, customers needing follow-up.
   - Patch progress pulse.
   - Data confidence / ingest freshness.
   - Top exceptions by customer and issue.
   - Fast click-through into Customer Health or Triage.

2. Customer Health
   - Current Org Overview reshaped as a one-customer report.
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
   - Blocker ownership/type: data confidence, MSP action, customer/user
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
   - Customer/exportable evidence.

Supporting dashboards:
- Patch Detail remains the KB/current-state drill-through page.
- Utilities remains broad activity search, but important search paths
  should be reachable from Triage.

# Functional coverage

- Customer Health
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

- Command Center ranks customers by the documented tier rules and shows
  the reason behind each tier.
- Customer Health answers the same health questions for one customer as
  an export-friendly report.
- Triage uses the documented priority order and exposes enough evidence
  for a junior tech to know what to check next.
- Device Drilldown shows full scope, scan, install, warning/failure,
  reboot, next-step, and Ninja-link evidence for the selected device.
- Trends shows patch progress and failure movement over the selected
  window.
- A real operator walkthrough can answer: which customers are unhealthy,
  which devices need work, what is blocking them, and where is the full
  evidence, without schema explanation.

# Steps

1. Lock dashboard naming/identity strategy, deployment/bootstrap behavior,
   old-to-new functional mapping, and speed baseline:
   - current dashboard/card query timing;
   - dashboard broad vs filtered load behavior;
   - existing click-through paths to preserve;
   - current bootstrap trigger after Portainer deploy;
   - concrete health-tier thresholds;
   - concrete within-tier customer ordering.
2. Audit current card SQL and identify reusable canonical result shapes:
   customer health, device triage, scan confidence, failure events.
3. Decide which shapes need materialized views for speed.
4. Add migration/view refresh plumbing if needed.
5. Rework Command Center into cross-customer health and exceptions.
6. Rework Org Overview into Customer Health while preserving existing
   customer click-through behavior.
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

first implementation slice complete locally:
- visible navigation labels changed to Customer Health and Triage while
  stored Metabase dashboard names remain stable;
- Command Center customer ranking now uses health tier + reason;
- Customer Health top band now answers enabled/scanned/installed/needs
  attention;
- Triage now has priority, blocker, warning-only rows, full messages,
  and message-text search.

Pending:
- live Metabase bootstrap;
- page-load timing;
- click-through validation against the running stack.
