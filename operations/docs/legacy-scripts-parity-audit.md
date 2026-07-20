# Legacy scripts parity audit — Agent Compliance + Software

**Purpose:** Inventory the pre-Operations PowerShell + Python scripts
in `..\..\script-dev\` that this stack was built to replace, and
classify each against current Operations coverage. Complements
`metabase-parity-audit.md` (which covers the *dashboard* layer) —
this doc covers the *scripted-workflow* layer.

**Method:** Read the scripts, extract their function (auth path,
data pulled, transformation applied, output produced, operator action
enabled), then compare against Operations state as of 0.69.0.

**Sources reviewed:**

- `script-dev/migrated/` — retired PowerShell scripts, mostly AC +
  cleanup + offboarding.
- `script-dev/ninja/` — active Ninja-side scripts (patching report,
  Windows deploy, SW Inventory tool).
- `script-dev/ninja/SW Inventory/analyze_inventory.py` — the
  PDQ-based software analyzer (3041 lines).

**Classification key:** same as `metabase-parity-audit.md`.

---

## Agent Compliance

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

### `migrated/Delete_All_Dup_Offline.ps1`, `Delete_MCS_Dup_Offline.ps1`, `Device_Cleanup.ps1`, `Ninja_S1_LMI_Cleanup_dups_offline_grp_by_client.ps1`, `_grp_by_tech.ps1`, `Remove_Ephemeral_Duplicates semi final.ps1`, `Report MCS Offline Devices.ps1`

Related dedup / offline cleanup automation. What they do:

- Query platform APIs for offline devices past a threshold.
- Cross-reference to find duplicates (same hostname across
  platforms, or same device offline in multiple).
- Delete or offboard the stale record via platform API.

**Classification: PARTIAL.**

- Operations *tracks* everything: `lifecycle_status` (active /
  offline_aging / pending_cleanup / retired), duplicate detection
  via the `duplicate_platform_record` Finding, generic device merge
  (0.67.0), and the operator-visible identity_conflict Finding
  (0.66.0).
- Operations *does not yet* trigger platform-side offboarding /
  deletion actions when an operator retires or merges a Device.
  Merges and lifecycle transitions are Operations-scoped and don't
  reach out to Ninja / S1 / LMI APIs to clean their side.
- Gap: **operator-triggered platform-side offboarding**. When an
  operator retires a Device in Operations, the loser side should
  be scheduled for platform-side cleanup (tag as offboarded in
  Ninja, decommission in S1, unassign in LMI). Currently the
  platform-side action requires re-running one of these scripts.

### `migrated/Ninja_set_offboard_tag_API.ps1`, `_2.ps1`, `offboard.ps1`, `Offboard_Computer.ps1`, `Offboard_Computer_UTA.ps1`, `S1_Decommission.ps1`

Platform-side offboarding actions:

- Set a Ninja offboard tag on a device via API.
- Decommission an agent in SentinelOne via API.

**Classification: GAP** (same as above). No Operations equivalent
today. The operator-triggered platform-side offboarding sits at the
end of the retirement/merge workflow.

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

- Consumes PDQ Inventory CSV exports (not Ninja API — different
  source, richer signal).
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
  installations). Would need a new join if this matters.
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
- **PDQ Inventory as a signal source** — Operations pulls software
  from Ninja only. PDQ provides different granularity (users,
  install paths, sizes). If PDQ signal is operationally valuable,
  a new ingest module would be needed.

---

## Aggregate gap summary

**Fully COVERED (retire the script — Operations does it end-to-end):**

- All AC checkers (multi-org + single-org).
- Both Ninja software pullers.

**PARTIAL — Operations tracks state, script's ancillary function is
the gap:**

- Bulk cleanup / dedup scripts — Operations tracks lifecycle and
  duplicates; the platform-side offboarding action is the gap.
- `analyze_inventory.py` — Operations covers data + decisions;
  CVE / user-risk / publisher rollups / Whitelist Suggestions
  surface / Excel-based UX / PDQ integration are gaps.

**GAP — no Operations equivalent:**

- Platform-side offboarding actions (Ninja tag, S1 decommission,
  LMI unassign) triggered from Operations lifecycle transitions.
- CVE / vulnerability enrichment on the software catalog.
- User-risk analysis (user ↔ software installation join).
- PDQ Inventory as a software signal source.

**Minor cross-cutting:**

- Downloadable CSV export on Operations fleet pages (findings,
  devices, software). Currently browser-only. Small addition,
  probably worth doing per operator ergonomic feedback.

---

## Recommended sequencing

1. **Immediate retirement candidates** (scripts have no operational
   necessity today): AC scripts, Ninja software pullers. Operations
   already replaced them.
2. **Small operational gap fixes** (bounded slices):
   - CSV export buttons on Operations fleet + findings pages.
   - Operator-triggered platform-side offboarding for Ninja / S1 /
     LMI (a small `retire_device` workflow that queues the platform
     actions).
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

---

## Method notes

- Not every legacy script was read in full — behavior was extracted
  from headers, config blocks, and identifiable function shapes.
  Deep-dive per script only when parity classification was
  ambiguous.
- Classifications reflect Operations state as of version 0.69.0.
- Operator ergonomic parity (Excel-vs-web UX, downloadable exports)
  is called out as a category of gap even where the data +
  decisions are functionally COVERED — worth naming for the
  retirement conversation.
- The audit is read-only: no scripts touched, no Operations
  behavior changed.
