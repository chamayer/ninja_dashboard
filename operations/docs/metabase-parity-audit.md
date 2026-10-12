# Metabase-to-Operations parity audit

**Status:** Decision-ready audit, 2026-10-12. This is an evidence inventory,
not a change to Metabase or Operations.

## Scope and method

This audit covers every card on the live Patching, Agent Compliance, and
Inventory dashboards. Live Metabase API metadata was inspected for active
dashboards and cards; archived Inventory dashboard/card metadata was inspected
read-only in the Metabase application database. Query text, results, customer
data, and credentials were not retrieved.

Operations routes and templates were inspected to identify the actual operator
surface, not a merely plausible data source. A semicolon-separated cell below
lists individual cards that share the same intent, destination, and outcome;
every live card name appears exactly once.

| Outcome | Meaning |
|---|---|
| **Displayed** | The card's operator question is shown directly on the linked Operations page. |
| **Consolidated** | Operations answers it in a combined operational view rather than a dedicated card. |
| **Missing** | The exact operator question has no native display and needs a scoped Operations refinement before that capability is retired. |
| **Retire** | The card belongs to an explicitly retired domain or disabled legacy workflow; no replacement is required. |

This follows root [ADR-0005](../../docs/decisions/0005-operations-first-metabase-retirement.md): Operations is the operator authority, Metabase is not reproduced card-for-card, and any future replacement must use generic Operations contracts rather than copied Metabase SQL.

## Patching — seven active dashboards

| Live dashboard | Card(s) and operator intent | Operations surface | Outcome |
|---|---|---|---|
| Ninja — Command Center | Fleet Approved Windows Devices; Fleet Active Windows Devices; Fleet Included Devices; Stalled Devices; Never-Patched Devices; Included Devices Actively Patching; Devices Awaiting Reboot; Recent Patch Activity (Fleet) — current fleet patch posture | [`/patching/`](/patching/) | Displayed |
| Ninja — Command Center | Approved Patches; Patches Awaiting Manual Approval; Delayed Patches; Patch Failures; OS Patch Warnings (24h); OS Patch Failures (24h); Failed Patch Devices; Manual or Delayed Patch Devices — work that needs attention | [`/patching/`](/patching/) and [`/findings/?category=patching`](/findings/?category=patching) | Consolidated |
| Ninja — Command Center | Data Freshness; Ingest Pipeline Status — whether the underlying Ninja evidence is current | [`/sources/`](/sources/) | Displayed |
| Ninja — Command Center | Clients Needing Attention — which clients require patch follow-up | [`/patching/`](/patching/) client posture table | Displayed |
| Ninja — Client Patch Review | Approved Windows Devices; Active Windows Devices; Included Devices; Devices Scanned Successfully (30d); Devices Installed Recently (30d); Devices Needing Action; Patch Failures; Approved Patches; Patches Awaiting Manual Approval; Delayed Patches; Stalled Devices; Never-Patched Devices; Patching Devices; Current Patch State; Devices Needing Reboot — one client's current patch posture | [`/patching/?client=<client-slug>`](/patching/) | Displayed |
| Ninja — Client Patch Review | Client Patch Status; Failed Patch Devices; Manual or Delayed Patch Devices; Warnings (30d); Failures (30d); Top Problem Devices — client triage summary | [`/patching/?client=<client-slug>`](/patching/) plus [`/findings/?category=patching&client=<client-slug>`](/findings/?category=patching) | Consolidated |
| Ninja — Client Patch Review | Fully patched % (patching devices) by Device Type; Fully patched % (patching devices) by Operating System — percentage breakdowns for a client | No native percentage-breakdown display | **Missing** |
| Ninja — Device Detail | Device Summary; Current Patch State; Install Results Over Time; Recent Patch & Reboot Activity; Patch State History; Install History; Recent OS Patch Warnings (30d); Recent OS Patch Failures (30d) — one device's patch evidence and history | [`/orgs/<client>/devices/<device>/` patching tab](/devices/) | Displayed |
| Ninja — Device Work Queue | Devices Needing Action; Never Patched; Stalled; Offline; Failed Installs; Reboot Pending; With Warnings; With Failures; Device Work Queue; Devices Needing Action by Client; Devices Needing Action by Problem; Scan Gaps; Devices Blocked by Reboot; Devices Blocked by Approval; Stalled or Never Patched — triage queue and reason | [`/patching/`](/patching/) | Displayed |
| Ninja — Device Work Queue | Warnings by Category (30d); Top Devices by Warnings (30d); Top Devices by Failures (30d); Failures by Error Code (30d); Devices Matching Warning Category (30d); Devices Matching Failure Error Type (30d) — filterable problem analysis | [`/patching/`](/patching/) and [`/patching/activity/`](/patching/activity/) | Consolidated |
| Ninja — Patch Evidence | Patch State; Patch Severity; Devices with Matching Patches; KBs with Matching Patches; Patch Install Results Over Time; All Devices with Matching Patches; All Matching KBs; Matching Patch Rows; Patch Evidence Table (top 500); Patch Types — filtered device/KB evidence | [`/patching/evidence/`](/patching/evidence/) | Displayed |
| Ninja — Patch Trends | Patch Installs per Day; Failed Install Attempts per Day; System Reboots per Day; Patching Devices per Day; Currently-MANUAL Patches by Age; OS Patch Warnings per Day; OS Patch Operational Failures per Day — trend and age analysis | [`/patching/trends/`](/patching/trends/) | Displayed |
| Ninja — Activity Search | Activity Search — find individual patch/install activity | [`/patching/activity/`](/patching/activity/) | Displayed |

### Patching conclusion

The operational patching surface is present. The only confirmed missing
capability is a *client-filtered fully-patched percentage* with two breakdowns
(device type and operating system). It is reporting context, not a separate
workflow or new authority. A future, bounded refinement should add that
breakdown to the existing Patching page's client posture section, using the
same patching population denominator already visible there. No Metabase work
is justified.

## Agent Compliance — twelve active legacy dashboards

Agent Compliance is disabled and must not regain a parallel authority. The
operator questions that remain meaningful are represented by Operations'
coverage, issues, client mapping, sources, and notification configuration
surfaces. Legacy alert delivery/debug mechanics are retirement candidates,
not missing Operations features.

| Live dashboard | Card(s) and operator intent | Operations surface | Outcome |
|---|---|---|---|
| Agent Compliance - Command Center | Compliant %; Devices to fix; Degraded devices; Services down — current coverage posture | [`/coverage/`](/coverage/) and [`/findings/?category=coverage`](/findings/?category=coverage) | Consolidated |
| Agent Compliance - Command Center | Names to map; Unmatched names — identity/mapping review backlog | [`/admin/integrations/client-mappings/`](/admin/integrations/client-mappings/) and [`/clients/candidates/`](/clients/candidates/) | Displayed |
| Agent Compliance - Alerts | First notifications ready to send; Alertable issues not sending a first notification; Recently notified; Open alertable device issues — legacy delivery queue/history | Open issues: [`/findings/?category=coverage`](/findings/?category=coverage); legacy delivery mechanics: none | Retire |
| Agent Compliance - Customers | Customers and platform names; Customer names to review; Platform names by customer; Ignored customer names — client mapping and coverage configuration | [`/inventory/clients/`](/inventory/clients/), [`/admin/integrations/client-mappings/`](/admin/integrations/client-mappings/), and client configuration | Consolidated |
| Agent Compliance - Debug | Raw observations; Same name across customers; Notification decision details; Recent device renames — legacy diagnostics | Generic source evidence/admin audit remains available; AC-specific diagnostic dashboard is not an operator surface | Retire |
| Agent Compliance - Device drilldown | Platform status; Recent state history; Open and recent issues; Ignores for this device — one device's coverage state | [`/orgs/<client>/devices/<device>/`](/devices/) and its linked Issues | Consolidated |
| Agent Compliance - Devices | Needs attention by customer; Needs attention by issue type; Needs attention by OS family; Needs attention by device type; Devices needing action; Missing but online somewhere else; Devices by missing platform; Suggested device name merges; Stale devices by customer; Ignored devices; All devices — filterable fleet coverage work | [`/devices/`](/devices/), [`/coverage/`](/coverage/), [`/findings/?category=coverage`](/findings/?category=coverage), and [`/merge-candidates/`](/merge-candidates/) | Consolidated |
| Agent Compliance - Health | Collection and delivery problems; All sources — source collection health | [`/sources/`](/sources/) and [`/admin/overview/`](/admin/overview/) | Consolidated |
| Agent Compliance - Health | Device issues by platform; Names needing review by platform — coverage/mapping workload by source/platform | [`/coverage/`](/coverage/) and [`/admin/integrations/client-mappings/`](/admin/integrations/client-mappings/) | Consolidated |
| Agent Compliance - Org Review | Names to map; Unmatched names; Ignored names — client/source mapping work | [`/admin/integrations/client-mappings/`](/admin/integrations/client-mappings/) | Displayed |
| Agent Compliance - Review | Names to map; Unmatched names; Ignored names; New Names — mapping/candidate review | [`/admin/integrations/client-mappings/`](/admin/integrations/client-mappings/) and [`/clients/candidates/`](/clients/candidates/) | Displayed |
| Agent Compliance - Setup | Required platforms; Customer alert setup; Alert rules; Notification routes; Sources; Add a per-customer ScreenConnect source — legacy configuration | [`/admin/requirement-profiles/`](/admin/requirement-profiles/), [`/admin/notifications/`](/admin/notifications/), and [`/sources/`](/sources/) | Consolidated |
| Agent Compliance - Source Health | Missing by platform; All sources — coverage gap/source freshness | [`/coverage/`](/coverage/) and [`/sources/`](/sources/) | Consolidated |
| Agent Compliance - Today | Total devices; Compliant devices; Compliant %; Missing; Offline; Review; Stale; Names to review; Collection issues; Needs attention by customer; Needs attention by issue type; Needs attention by OS family; Needs attention by device type; Top device issues; Customer names needing review; Collection and delivery problems — today's fleet coverage work | [`/coverage/`](/coverage/), [`/findings/?category=coverage`](/findings/?category=coverage), [`/sources/`](/sources/), and mappings | Consolidated |
| Agent Compliance - Today | Ready to notify — legacy notification dispatch condition | Notifications are configured in Operations but legacy AC delivery state is intentionally retired | Retire |

### Agent Compliance conclusion

No new Agent Compliance-specific page should be built. Its active dashboards
are legacy read models; the live operator paths are already consolidated in
Operations. Before archiving the remaining dashboards, the owner only needs
to accept retirement of the legacy notification-delivery and debug cards—not
an implementation project.

## Inventory — five archived dashboards

All five are already archived in live Metabase. The owner accepted their
retirement on 2026-08-03 in ADR-0005, without an Operations parity gate.
Their individual cards are retained here so the audit is complete.

| Archived dashboard | Card(s) | Operations surface / decision | Outcome |
|---|---|---|---|
| Inventory - Overview | Resolved devices; Managed devices; Missing coverage; Unresolved records; Identity conflicts; Merge candidates; Inventory states; Devices by platform; Inventory attention | Accepted Inventory retirement; useful navigation remains in [`/devices/`](/devices/), [`/coverage/`](/coverage/), and review queues | Retire |
| Inventory - Devices | Total matching devices; Total matching customers; Device inventory (top 500); Inventory by customer (top 300) | Accepted Inventory retirement; device/client navigation remains in Operations | Retire |
| Inventory - Identity Review | Total identity conflicts; Identity conflicts (top 300); Total merge candidates; Merge candidates (top 300) | Accepted Inventory retirement; current review paths are [`/merge-candidates/`](/merge-candidates/) and [`/clients/candidates/`](/clients/candidates/) | Retire |
| Inventory - Serial Quality | Serial quality by platform; Total matching serial records; Serial quality details (top 500) | Explicitly deferred generic data-quality capability; does not gate retirement | Retire |
| Inventory - Source Records | Total unresolved / excluded records; Unresolved / excluded source records (top 500); Total matching source observations; Current source observations (top 500) | Explicitly deferred generic source-evidence administration capability; does not gate retirement | Retire |

## Recommendation

1. **Accept Patching parity with one bounded follow-up:** add the two missing
   fully-patched percentage breakdowns to the existing Patching client posture
   view. Do not add a Patching dashboard or duplicate calculations.
2. **Accept Agent Compliance retirement:** archive the 12 remaining active
   dashboards after the owner accepts retirement of the legacy delivery and
   debug cards. No AC-specific replacement is recommended.
3. **Keep Inventory retired:** its five archived dashboards remain outside the
   parity gate, as already accepted. Serial quality and generic source evidence
   remain separately prioritized Operations work, not Metabase recreation.
4. **Only after those decisions:** perform a separate, explicitly approved
   cutover that archives/disconnects the accepted Metabase domains while
   preserving legacy data for rollback. This audit makes no production change.

## Evidence and limits

- Live metadata on 2026-10-12: 7 active Patching dashboards, 12 active Agent
  Compliance dashboards, and 5 archived Inventory dashboards.
- The live card inventory is the source for the rows above. The older
  [`metabase-parity-audit-full.md`](./metabase-parity-audit-full.md) is useful
  historical bootstrap evidence but is not authoritative for live card counts
  or names.
- Exact client/device deep links require a selected client or device. Route
  placeholders are intentional and do not imply a hard-coded tenant/client.
