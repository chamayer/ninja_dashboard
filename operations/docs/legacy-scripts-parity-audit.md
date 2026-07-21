# Legacy scripts parity audit

**Purpose:** Inventory the pre-Operations PowerShell + Python scripts
in `..\..\script-dev\` that this stack was built to replace, and
classify each against current Operations coverage. Complements
`metabase-parity-audit.md` (which covers the *dashboard* layer) —
this doc covers the *scripted-workflow* layer.

**Method:** Read the scripts, extract their function (auth path,
data pulled, transformation applied, output produced, operator action
enabled), then compare against Operations state as of 0.69.0.

**Sources reviewed:**

- `script-dev/migrated/` — retired PowerShell scripts (AC, cleanup,
  offboarding, software pullers, ad-hoc experiments).
- `script-dev/ninja/` — active Ninja-side scripts (patching report,
  Windows deploy, SW Inventory tool).
- `script-dev/ninja/SW Inventory/analyze_inventory.py` — the
  PDQ-based software analyzer (3041 lines).
- `script-dev/ad/`, `script-dev/clients/{ADH,CP,UTA}/` — AD / Entra
  user-management scripts and per-client data.
- `script-dev/sentinelone/`, `script-dev/windows/` — small utility
  scripts.

**Classification key:** same as `metabase-parity-audit.md`.

---

## Agent Compliance

**Status note (verified 2026-07-21):** the legacy AC ingest module in
`ingest/agent_compliance/` no longer auto-runs — `ingest/main.py`
scheduler explicitly excludes it ("Legacy AC remains available by
manual endpoint during cutover, but no longer auto-runs"). Data in
`ninja_agent_compliance.*` tables therefore goes stale unless
someone manually triggers a run. Operations native path
(source_observations + identity resolver + platform evaluator) is
the live surface. Retirement of the legacy AC module + schema is a
bounded destructive slice when ready.

### `migrated/Multi_org_agent_compliance.ps1` (1972 lines)

Cross-platform multi-org AC checker. What it does:

- Auths against Ninja / SentinelOne / ScreenConnect / LogMeIn.
- Fetches all devices/agents from each platform.
- Groups by (org + hostname) composite key.
- Applies per-org `RequiredPlatforms` + stale-age thresholds.
- Emits a CSV compliance matrix + a summary CSV.
- Reports missing-agent counts per device (report-only, no
  remediation action).

**Classification: COVERED.** Everything this script produces is
native in Operations:

- **Continuous multi-source ingestion** → `ingest/` modules per
  platform. No batch script runs.
- **Per-org required platforms** → `RequirementProfile` +
  `RequirementProfileItem` (admin-editable, per-Client assignment).
- **Per-platform stale-age thresholds** → `Agent` seed rows
  (`default_gap_after_hours`, `default_confidence_probable`,
  `default_confidence_confirmed`).
- **Compliance matrix per device** → `device_agent_presence_current`
  matview + `v_device` view.
- **Missing-agent per device** → `missing_ninja` / `missing_sentinelone`
  / `missing_logmein` / `missing_screenconnect` Findings.
- **CSV export** — findings queue supports filtering; a CSV export
  button on the fleet page is a potential small gap if operators
  still depend on exportable matrices for offline review. Note as
  minor.

### `migrated/Agent-Compliance_Single ORG.ps1` (700 lines)

Single-org variant of the above (predates the multi-org rewrite).

**Classification: COVERED.** Same rationale. Subset of Multi-org.

### `migrated/Delete_All_Dup_Offline.ps1`, `Delete_MCS_Dup_Offline.ps1`, `Device_Cleanup.ps1`, `Ninja_S1_LMI_Cleanup_dups_offline_grp_by_client.ps1`, `_grp_by_tech.ps1`, `Remove_Ephemeral_Duplicates semi final.ps1`, `Report MCS Offline Devices.ps1`, `migrated/Ninja_set_offboard_tag_API.ps1`, `_2.ps1`, `offboard.ps1`, `Offboard_Computer.ps1`, `Offboard_Computer_UTA.ps1`, `S1_Decommission.ps1`

Related dedup + platform-side offboarding automation:

- Query platform APIs for offline devices past a threshold.
- Cross-reference to find duplicates.
- Delete / offboard the stale record via the source platform's API
  (set a Ninja offboard tag, decommission an agent in SentinelOne,
  etc.).

**Classification: OUT OF SCOPE for Operations parity.**

- The *detection / tracking* side is COVERED in Operations —
  `lifecycle_status` (active / offline_aging / pending_cleanup /
  retired), the `duplicate_platform_record` Finding, the generic
  `device_merge` action (0.67.0), and the `identity_conflict`
  Finding (0.66.0). Operations knows which devices are candidates
  for cleanup.
- The *platform-side action* — reaching back into Ninja / S1 / LMI
  APIs to actually delete / decommission / untag — is deliberately
  outside Operations' scope. Operations is a monitoring +
  operator-decision surface; it does not orchestrate writes into
  the source platforms. These scripts remain the tooling for that.
- No parity requirement. Scripts stay.

---

## Software

### `migrated/Ninja_sw_inventory.ps1` (70 lines) + `Ninja_sw_inventory_org.ps1` (96 lines)

Ad-hoc Ninja software-inventory pullers:

- Auths against Ninja.
- Fetches all agent devices (optionally filtered by org + hostname
  prefix).
- For each device, pulls the installed-software list from Ninja.
- Filters by software name pattern.
- Outputs a flat list (console or CSV).

**Classification: COVERED.** Superseded by continuous ingestion:

- **Continuous pull** → `ingest/inventory/software.py` runs on
  interval and populates `operations.software_installations_current`
  matview per (device, canonical_name).
- **Per-device software list** → Device detail page has a software
  tab (part of the 5-tab detail).
- **Filter by software name** → Software fleet page + software
  decisions queue support name filtering.
- **Per-org / per-client scoping** → all queries are Client-scoped
  by default.
- **CSV/export for ad-hoc reporting** — same minor gap as AC
  (browser export vs downloadable CSV).

### `ninja/SW Inventory/analyze_inventory.py` (3041 lines) + `.md` brief

This is the substantial one. It's not just a data puller — it's a
per-client software-risk analyzer with an Excel-based decision
workflow. What it does:

- Consumes a Ninja-side CSV export produced by
  `Ninja_sw_inventory.ps1` (same data Operations already ingests
  continuously via `ingest/inventory/software.py` — the CSV was
  just the offline export format the analyzer read).
- Per-client `.xlsx` workbook with sheets: Summary, CVE Details,
  User Risk, Whitelist Suggestions, Action List (Software),
  Action List (Publishers), Approved, Tech Checklist, All Software,
  _Decisions.
- Classification engine: WHITELIST (exact match), TRUSTED_PUBLISHERS
  (substring), SUSPICIOUS_NAMES / SUSPICIOUS_PATHS patterns, plus
  operator decisions (Approve / Approve Publisher / Reject /
  Investigate) that override.
- CVE lookups (NVD / VirusTotal / MetaDefender toggles).
- User-risk analysis (which users have suspicious software).
- Whitelist suggestions (software installed on ≥ threshold
  machines gets suggested for whitelisting).
- Publisher rollups.
- In-workbook VBA decision buttons that write back to
  `decisions_global.csv` / `decisions_{client}.csv` — merges, never
  overwrites.
- Rare-install detection (software on ≤ 2 machines).
- Tech Checklist (actionable per-device list).
- Publishes as `.xlsm` via VBS macro injection so operators get
  clickable decision UX in Excel.

**Classification: PARTIAL / GAP.**

**COVERED by Operations today:**

- Software catalog + per-device installation tracking →
  `operations.software_catalog`, `operations.software_installations_current`.
- Software decisions layer → `operations.software_decisions` +
  `SoftwareClassifierRule` admin (Track UI-2.C).
- Software fleet page → covers "All Software" browsing.
- Software decisions queue → covers Whitelist Suggestions review
  workflow (though not Excel-based).
- Approve / Reject / Investigate decisions → available in the
  decisions queue UI.
- Per-client scoping → all queries are Client-scoped.
- Rare-install signal → `rare_recent` Finding shipped in 0.60.0.

**GAPS (no Operations equivalent today):**

- **CVE lookup / vulnerability enrichment** (NVD / VirusTotal /
  MetaDefender). Operations has no CVE integration. The classifier
  is pattern-based only.
- **User-risk analysis** — Operations doesn't associate installed
  software to users (ClientUser exists but isn't linked to
  installations). Wire the `lastLoggedInUser` field Ninja publishes
  per device.
- **Publisher rollups** — Operations has publisher data in the
  catalog but no dedicated rollup view / decision surface *for
  publisher-level decisions* beyond the software classifier's
  substring-match feature.
- **Tech Checklist** (actionable per-device software cleanup list) —
  no direct equivalent. The Findings queue with software category
  filter is the closest analog, but the Tech Checklist is a curated
  cross-reference of decisions + rare software + suspicious matches.
- **Whitelist Suggestions surface** with threshold-based auto-
  suggest — Operations classifier suggests via rules, but doesn't
  produce a "these N software titles are on ≥ X machines and
  currently unclassified" suggestion queue.
- **Excel / VBA / VBS output pipeline** — Operations is web-only.
  Operators who preferred the Excel decision workflow lose that
  interaction pattern. The web decisions queue is functionally
  equivalent but different UX.

---

## Patching

### `ninja/Ninja-Patching-report.ps1` (559 lines)

Generates a full patch-management CSV with one row per (device,
patch). What it does:

- Auths against Ninja.
- Pulls organizations, locations, policies (for lookup).
- Pulls `/queries/os-patch-installs` (INSTALLED + FAILED patches
  via cursor pagination).
- Pulls `/queries/os-patches` (PENDING / APPROVED / REJECTED via
  cursor pagination).
- Pulls `/devices-detailed` (device metadata).
- Joins the four into a wide row: Organization, Location,
  DeviceName, NodeClass, OS, OSMajorVersion, IPAddress, LastUser,
  OnlineStatus, LastContact, LastContactDaysAgo, LastBoot,
  LastBootDaysAgo, NeedsReboot, PolicyName, PatchName, KBNumber,
  Status, Severity, Type, InstalledAt, DaysSinceInstall.
- Outputs a timestamped CSV in the script directory.
- Filters: `$FilterOrgs`, `$WorkstationsOnly`, `$ServersOnly`.

**Classification: PARTIAL.**

- **Data COVERED.** Every column above is populated in the
  Operations pipeline: `ninja_core.device_snapshots`,
  `ninja_core.patch_state_current` (or equivalent patching
  matviews), `operations.devices`, `operations.device_links`,
  `device_session_current`. Nothing new needs to be ingested.
- **Composite view COVERED partially.** The Ninja patching
  dashboards in Metabase render subsets of this composite (per
  `metabase-parity-audit.md`). Operations natively has the
  Findings queue with `category=patching`, Device detail's
  Patching tab, and the Devices fleet page — but no single
  "wide row per (device, patch)" table with all the columns
  above.
- **CSV output GAP.** Same downloadable-CSV cross-cutting gap
  named in the AC + Software section. If operators still expect a
  bulk CSV extract per patch cycle, Operations needs an export
  route.
- The 3 Ninja patching dashboards flagged as GAP in
  `metabase-parity-audit.md` (Patch Evidence, Patch Trends,
  Activity Search) are the surfaces closest to this script's
  intent. A single "Patch Evidence" fleet-wide table view in
  Operations would subsume the script's use case.

### `ninja/Deploy-Win11-InPlace.ps1`

In-place Windows 11 deployment tool.

**Classification: OUT OF SCOPE.** This is a device-side automation
utility, not a monitoring/compliance function. Operations does not
plan to orchestrate OS-deployment actions from its surface. Leave
it in `script-dev/` as an operational tool.

### `ninja/Get S1 Server URL.ps1`

Small helper to resolve the SentinelOne management server URL for
a given device.

**Classification: OUT OF SCOPE.** Ad-hoc utility, not a
monitoring function.

---

## Directory management (AD / Entra)

### `ad/ADH-User-Management-current.ps1`, `migrated/ADH-User managhement- current.ps1`, `ad/AD-Test-Creds-Prompt.ps1`, `ad/AD-Unlock.ps1`

Active Directory user-management scripts:

- Create / update / unlock AD user accounts.
- Test credentials against a domain controller.

**Classification: OUT OF SCOPE.** Operations is device / agent /
software focused. User-account lifecycle in AD or Entra is a
different domain and not on the current MSP-platform roadmap for
Operations. Leave these scripts as their own tooling.

### `clients/CP/*` — AD ↔ Entra hybrid-identity reconciliation

`Compare-HybridIdentities.ps1` + `Get-AdUserDump.ps1` +
`Get-EntraUserDump.ps1` plus periodic CSV snapshots and an Excel
reconciliation workbook (`cp-reconciled.xlsx`).

**Classification: OUT OF SCOPE.** Same domain concern as AD user
management. Per-client one-off tooling. If hybrid-identity
reconciliation becomes an MSP-platform requirement, it'd be its
own track with its own decision record.

### `clients/UTA/offboard-computer.ps1`

Per-client offboarding script.

**Classification: PARTIAL** (same as the `migrated/` offboarding
scripts). Rolls up under the "operator-triggered platform-side
offboarding" gap.

---

## Small utilities

### `sentinelone/Get defender status.ps1`

Small S1 API helper to check Windows Defender status per device.

**Classification: OUT OF SCOPE.** Ad-hoc utility. If Defender
status becomes an operational signal Operations should track,
it'd flow through the SentinelOne ingest module, not this script.

### `windows/Windows-Check_User_logged_in.ps1`

Local Windows utility to check the current logged-in user.

**Classification: OUT OF SCOPE.** Device-side utility, not a
monitoring function.

### `migrated/Ninja_auth.ps1`, `Ninja_auth_Accessrt.ps1`

OAuth token-fetcher utilities for the Ninja API.

**Classification: COVERED.** Every Operations / ingest connector
handles its own auth. These are historical helpers, no parity
required.

### `migrated/Untitled*.ps1` (numerous)

Ad-hoc experimentation files — Untitled1.ps1 through Untitled42.ps1
etc. No stable identity, no operational role.

**Classification: N/A.** Skipped from the audit. If any specific
`Untitled*` script encodes a workflow the operator still relies
on, name it explicitly and it'll get its own row.

### `clients/ADH/`, `general/`, `logmein/`, `screenconnect/`, `utility/`

Empty or effectively empty at audit time.

**Classification: N/A.**

---

## Aggregate summary

Scripts are operational tools; none are slated for retirement.
Operations' role is monitoring + operator decisions on top of the
data. Where a script's function has moved into Operations, the
script becomes optional (nobody has to run it), but it stays
available.

**Fully COVERED — Operations replaces the monitoring / reporting
function of the script (the script itself stays as tooling):**

- All AC checkers (multi-org + single-org).
- Both Ninja software pullers.
- Ninja auth utilities (every ingest connector auths itself).

**PARTIAL — Operations tracks the state or has close analogs; a
specific presentation or capability is still only in the script:**

- `analyze_inventory.py` — Operations covers software data +
  decisions + rare_recent + classifier rules. Still only in the
  script: CVE / vulnerability enrichment, user-risk analysis (user
  ↔ installation join), publisher rollups + publisher-level
  decision surface, Whitelist Suggestions surface with
  threshold-based auto-suggest, Tech Checklist, PDQ Inventory as
  a distinct signal source, Excel/VBA output pipeline.
- `Ninja-Patching-report.ps1` — every column it produces exists in
  the Operations pipeline. What's still only in the script: the
  wide "one row per (device, patch)" composite table + CSV export.
  Overlaps with the three Ninja patching Metabase-dashboard GAPs
  (Patch Evidence, Patch Trends, Activity Search).

**Data-quality operator-visible surfaces (may or may not be gaps —
please confirm):**

- **Placeholder / shared-serial devices list.** The resolver
  already handles the correctness case (`is_usable_serial` prevents
  placeholders from driving identity matches). The retired
  `identity_candidates_list` page had a separate operator-visible
  list of *which devices currently have placeholder or shared
  serials* — a data-quality report. That surface does not exist in
  current Operations. **Confirm whether this needs an equivalent
  or the correctness gate alone is sufficient.**
- **Unmatched source records** — same shape: the retired page had
  a summary count of unmatched source groups. Currently only
  visible from ingest logs.

**OUT OF SCOPE — Operations was never intended to cover these:**

- **Platform-side actions** (offboard tag in Ninja, decommission
  in S1, unassign in LMI, delete a duplicate). The cleanup and
  offboarding scripts remain the tooling for platform-side writes.
  Operations is monitoring + operator decisions, not a write-back
  orchestrator into the source platforms.
- AD / Entra user-account management (`ad/*`, `migrated/ADH-User*`).
- AD ↔ Entra hybrid-identity reconciliation
  (`clients/CP/Compare-HybridIdentities.ps1` + friends).
- OS-deployment automation (`Deploy-Win11-InPlace.ps1`).
- Small device-side utilities (`Get defender status.ps1`,
  `Windows-Check_User_logged_in.ps1`, etc.).

**Minor cross-cutting:**

- Downloadable CSV export on Operations fleet pages (findings,
  devices, software, patches). Currently browser-only. Small
  addition, probably worth doing per operator ergonomic feedback.
- Ad-hoc `Untitled*.ps1` experimentation files were not audited —
  no stable identity.

---

## Recommended sequencing (Operations build work only)

1. **Small operational fixes** (bounded slices):
   - CSV export buttons on Operations fleet + findings + patch
     pages.
   - Confirm and (if needed) build the data-quality list surfaces
     (placeholder/shared serials, unmatched source groups).
2. **Patching visibility track** — closes the Metabase-parity gaps
   and subsumes `Ninja-Patching-report.ps1`'s intent:
   - Fleet Patch Evidence view — wide (device × patch) composite
     rendered as an Operations page.
   - Patch Trends views (per-day install/failure/reboot volumes).
   - Activity Search (patch-activity free-text search).
3. **Software-analyzer gap track** (larger, its own decision
   record):
   - Publisher rollups + publisher-level decision surface.
   - Whitelist Suggestions surface (threshold-based auto-suggest of
     unclassified software).
   - Tech Checklist as an Operations report / view.
   - CVE enrichment (integrate NVD or equivalent).
   - User-risk analysis (only if user ↔ installation join is
     operationally valuable).
   - PDQ ingestion if that source's granularity is needed.
   - **Explicitly not planned:** Excel / VBA output. Operations is
     web-only.
4. **Explicitly not planned:** Platform-side write actions, AD /
   Entra user management, hybrid identity reconciliation,
   OS-deployment orchestration. Scripts stay for these.

---

## Method notes

- Not every legacy script was read in full — behavior was extracted
  from headers, config blocks, and identifiable function shapes.
  Deep-dive per script only when parity classification was
  ambiguous.
- Classifications reflect Operations state as of version 0.69.0.
- Operator ergonomic parity (Excel-vs-web UX, downloadable exports)
  is called out as a category of gap even where the data +
  decisions are functionally COVERED. Scripts stay; the gap-
  naming is about whether Operations should grow the equivalent
  UX, not about turning any script off.
- The audit is read-only: no scripts touched, no Operations
  behavior changed.
