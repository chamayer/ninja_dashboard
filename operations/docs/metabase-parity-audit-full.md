# Metabase parity audit — full metric enumeration

One row per named Metabase spec (card, metric, or component) in the three bootstrap modules. Grouping is best-effort by nearest preceding dashboard identifier reference. Companion to `metabase-parity-audit.md`.


## Ninja patching — `ingest/metabase_bootstrap.py` (123 specs)


### Ninja — Client Patch Review

| Line | Metric / card |
|---|---|
| 1079 | Failed Patch Queue |
| 1722 | Client Fully Patched Devices |
| 1789 | Devices Needing Reboot |
| 4326 | Devices Matching Failure Error Type (30d) |
| 4461 | Approved Windows Devices |
| 4478 | Active Windows Devices |
| 4493 | Client Status |
| 4563 | Included Devices |
| 4587 | Devices Scanned Successfully (30d) |
| 4612 | Devices Installed Recently (30d) |
| 4637 | Devices Needing Action |
| 4669 | Failed Patches |
| 4690 | Approved Patches |
| 4711 | Manual Approval |
| 4732 | Delayed Patches |
| 4753 | Stalled Devices |
| 4770 | Never-Patched Devices |
| 4786 | Patching Devices |
| 4803 | Current Patch State |

### Ninja — Device Detail

| Line | Metric / card |
|---|---|
| 1209 | Recent Patch Activity (Fleet) |
| 1240 | Ingest Pipeline Status |
| 1345 | Actively patching % |
| 1354 | Fully patched % (patching devices) |
| 1363 | Actively patching |
| 1372 | Fully patched |
| 1381 | Total Devices |
| 2381 | KBs by Patch Count |
| 2407 | Install Results Over Time |
| 2437 | All Devices by Patch Count |
| 2468 | All KBs by Count |
| 2496 | Total matching patch rows |
| 2515 | Patch Detail Table (top 500) |
| 2561 | Patches by Type |
| 2656 | Device Summary |
| 2762 | Current Patch State |
| 2787 | Install Results Over Time |
| 2809 | Recent Patch & Reboot Activity |
| 2839 | Patch State History |
| 3478 | All Devices by Patching Status |
| 3533 | Patch Count Source Check |
| 3708 | Total Issues |
| 3724 | Never Patched |
| 3740 | Stalled |
| 3756 | Offline |
| 3772 | Failed Installs |
| 3788 | Reboot Pending |
| 3810 | With Warnings |
| 3826 | With Failures |
| 3842 | Triage Queue |
| 3933 | Issues by Client |
| 3962 | Issues by Type |
| 3988 | Scan Gaps |
| 4020 | Reboot Blockers |
| 4048 | Approval Backlog |
| 4083 | Stalled or Never Patched |
| 4118 | Warnings by Category (30d) |
| 4162 | Top Devices by Warnings (30d) |
| 4191 | Top Devices by Failures (30d) |
| 4223 | Failures by Error Code (30d) |
| 4274 | Devices Matching Warning Category (30d) |
| 5036 | Devices Needing Reboot |

### Ninja — Device Patching Status

| Line | Metric / card |
|---|---|
| 701 | Fleet Approved Windows Devices |
| 1602 | Stalled Devices |
| 1624 | Never-Patched Devices |
| 1647 | Current Patch State |
| 3256 | Stalled Devices |
| 3278 | Never-Patched Devices |
| 3300 | Patching Status |
| 3327 | Patching Status by Device Type |
| 3353 | Patching Status by Operating System |
| 3392 | Patching Status by Organization |
| 3422 | Problem Devices - Triage Queue |

### Ninja — Device Work Queue

| Line | Metric / card |
|---|---|
| 774 | Never-Patched Devices |
| 794 | Included Devices Actively Patching |
| 806 | Approved Patches |
| 915 | OS Patch Failures (24h) |
| 933 | Data Freshness |
| 964 | Clients Needing Attention |
| 1464 | Failures (30d) |
| 1486 | Approved Patches |

### Ninja — Patch Evidence

| Line | Metric / card |
|---|---|
| 719 | Fleet Active Windows Devices |
| 735 | Fleet Included Devices |
| 754 | Stalled Devices |
| 828 | Patches Awaiting Manual Approval |
| 850 | Delayed Patches |
| 872 | Patch Failures |
| 897 | OS Patch Warnings (24h) |
| 1119 | Manual and Delayed Patches |
| 1165 | Patches Installed Awaiting Reboot |
| 1399 | Active Devices |
| 1419 | Data Freshness |
| 1446 | Warnings (30d) |
| 1508 | Manual Approval |
| 1530 | Delayed Patches |
| 1552 | Failed Patches |
| 1580 | Patching Devices |
| 1684 | Clients with Lowest Fully Patched Devices % |
| 1815 | Ingest Status (last 24h) |
| 2867 | Install History |
| 2902 | Recent OS Patch Warnings (30d) |
| 2939 | Recent OS Patch Failures (30d) |
| 3218 | Active Devices |
| 3234 | Patching Devices |
| 4841 | Fully patched % (patching devices) by Device Type |
| 4854 | Fully patched % (patching devices) by Operating System |
| 4867 | Failed Patch Queue |
| 4905 | Manual and Delayed Patches |
| 4948 | Warnings (30d) |
| 4964 | Failures (30d) |
| 4988 | Top Problem Devices |
| 5136 | Patch Installs per Day |
| 5163 | Failed Install Attempts per Day |
| 5194 | System Reboots per Day |
| 5224 | Active Devices Seen per Day |
| 5252 | Fully patched % (patching devices) per Day |
| 5266 | Patching Devices per Day |
| 5280 | Currently-MANUAL Patches by Age |
| 5321 | OS Patch Warnings per Day |
| 5356 | OS Patch Operational Failures per Day |
| 5601 | Activity Search |

### Ninja — Patch Trends

| Line | Metric / card |
|---|---|
| 2303 | Current Patch State |
| 2332 | Severity Breakdown |
| 2355 | Devices by Patch Count |

## Inventory — `ingest/inventory/metabase_bootstrap.py` (24 specs)


### Inventory - Devices

| Line | Metric / card |
|---|---|
| 174 | Managed devices |
| 186 | Missing coverage |
| 198 | Unresolved records |
| 244 | Devices by platform |
| 259 | Inventory attention |
| 293 | Total matching devices |
| 321 | Total matching customers |
| 339 | Device inventory (top 500) |
| 386 | Inventory by customer (top 300) |

### Inventory - Identity Review

| Line | Metric / card |
|---|---|
| 220 | Merge candidates |
| 231 | Inventory states |
| 421 | Total identity conflicts |
| 431 | Identity conflicts (top 300) |
| 459 | Total merge candidates |
| 473 | Merge candidates (top 300) |

### Inventory - Overview

| Line | Metric / card |
|---|---|
| 163 | Resolved devices |

### Inventory - Serial Quality

| Line | Metric / card |
|---|---|
| 513 | Serial quality by platform |
| 540 | Total matching serial records |
| 564 | Serial quality details (top 500) |

### Inventory - Source Records

| Line | Metric / card |
|---|---|
| 209 | Identity conflicts |
| 615 | Total unresolved / excluded records |
| 629 | Unresolved / excluded source records (top 500) |
| 661 | Total matching source observations |
| 685 | Current source observations (top 500) |

## Agent Compliance — `ingest/agent_compliance/metabase_bootstrap.py` (87 specs)


### Agent Compliance - Alerts

| Line | Metric / card |
|---|---|
| 389 | Ignored devices |
| 1080 | Alert rules |
| 1127 | Customer alert setup |
| 1178 | First notifications ready |
| 1213 | Active findings |
| 1262 | Recent deliveries |
| 1930 | Names to review |
| 2825 | First notifications ready to send |
| 2866 | Alertable issues not sending a first notification |
| 2905 | Recently notified |
| 2936 | Open alertable device issues |

### Agent Compliance - Customers

| Line | Metric / card |
|---|---|
| 378 | Current findings |
| 1317 | Customers and platform names |
| 1388 | Customer names to review |
| 1500 | Customer names by platform |
| 1521 | Required coverage |
| 1635 | Ignored customer names |
| 1941 | Collection issues |
| 2147 | Collection and delivery problems |
| 2972 | Customers and platform names |
| 3040 | Customer names to review |
| 3089 | Platform names by customer |
| 3109 | Ignored customer names |

### Agent Compliance - Debug

| Line | Metric / card |
|---|---|
| 1763 | Raw observations |
| 1783 | Same name across customers |
| 3431 | Raw observations |
| 3451 | Same name across customers |

### Agent Compliance - Device drilldown

| Line | Metric / card |
|---|---|
| 531 | All current devices |
| 626 | Missing but online elsewhere |
| 832 | Stale devices by customer |
| 878 | Ignored |
| 926 | Per-run state |
| 974 | Findings history |
| 1004 | Alert deliveries |
| 1038 | Ignore history |
| 2126 | Customer names needing review |
| 2426 | Missing but online somewhere else |
| 2585 | All devices |
| 2660 | Platform status |
| 2723 | Recent state history |
| 2747 | Open and recent issues |
| 2780 | Ignores for this device |
| 3483 | Notification decision details |
| 3504 | Recent device renames |

### Agent Compliance - Devices

| Line | Metric / card |
|---|---|
| 345 | Devices to fix |
| 356 | Source work |
| 400 | New customer names found |
| 432 | Need action |
| 692 | Active gaps by missing platform |
| 749 | Active platform gap details |
| 1843 | Compliant devices |
| 1856 | Compliant % |
| 1871 | Missing |
| 1883 | Offline |
| 1895 | Review |
| 1907 | Stale |
| 1919 | Ready to notify |
| 1984 | Needs attention by issue type |
| 2021 | Needs attention by OS family |
| 2053 | Needs attention by device type |
| 2085 | Top device issues |
| 2179 | Needs attention by customer |
| 2214 | Needs attention by issue type |
| 2254 | Needs attention by OS family |
| 2289 | Needs attention by device type |
| 2324 | Devices needing action |
| 2455 | Devices by missing platform |
| 2482 | Suggested device name merges |
| 2522 | Stale devices by customer |
| 2551 | Ignored devices |

### Agent Compliance - Health

| Line | Metric / card |
|---|---|
| 367 | Customer names to review |
| 1694 | Missing by platform |
| 1724 | Source work |
| 1741 | All sources |
| 1952 | Needs attention by customer |
| 3337 | Collection and delivery problems |
| 3355 | All sources |
| 3373 | Device issues by platform |
| 3412 | Names needing review by platform |

### Agent Compliance - Setup

| Line | Metric / card |
|---|---|
| 3167 | Required platforms |
| 3217 | Customer alert setup |
| 3245 | Alert rules |
| 3278 | Notification routes |
| 3294 | Sources |
| 3314 | Add a per-customer ScreenConnect source |

### Agent Compliance - Today

| Line | Metric / card |
|---|---|
| 331 | Compliant % |
| 1832 | Total devices |

---

Total specs across all three files: **234**
