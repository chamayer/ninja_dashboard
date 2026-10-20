# Dashboard Placement Map

Status: draft for review before implementation.

Timing baseline captured 2026-07-02 from live Metabase card-query API
with no filters and response output discarded. Times are API response
times, not full browser render times. HTTP `202` is the normal Metabase
query response observed during the sweep.

# Hard Decisions

- `Overall Patching Status`: remove from primary navigation after useful
  cards are moved or dropped.
- `Device Patching Status`: remove from primary navigation. Its useful
  content belongs in `Command Center`, `Device Work Queue`, or
  `Client Patch Review`; the only broad device table is also a slow
  page-load risk.
- Duplicate `Utilities`: keep one dashboard as `Activity Search`; hide
  or remove the duplicate.
- Card titles use scope prefixes only where ambiguity exists.

# Timing Risks

| Dashboard | Card ID | Card | Baseline | Decision |
|---|---:|---|---:|---|
| Overall Patching Status | 218 | Clients with Lowest Fully Patched Devices % | 2361ms | Merge into Command Center only if still needed. |
| Overall Patching Status | 219 | Client Fully Patched Devices | 6368ms | Do not carry forward as-is. Replace with focused client ranking. |
| Overall Patching Status | 266 | Fully patched % (patching devices) | 2130ms | Drop from primary nav unless rewritten. |
| Client Patch Status | 232 | Fully patched % by Device Type | 1697ms | Keep client-scoped only if useful after naming cleanup. |
| Client Patch Status | 233 | Fully patched % by Operating System | 1824ms | Keep client-scoped only if useful after naming cleanup. |
| Device Drilldown | 245 | Device Summary | 13984ms | Must optimize or guard behind selected device before implementation. |
| Device Patching Status | 259 | All Devices by Patching Status | 11183ms | Remove from primary nav; replace with Device Work Queue filters. |
| Patch Trends | 263 | Active Devices Seen per Day | 6621ms | Keep only if optimized or delayed from first view. |
| Patch Trends | 268 | Fully patched % per Day | >15000ms timeout | Must optimize before remaining in primary nav. |
| Patch Trends | 262 | System Reboots per Day | 1587ms | Watch; acceptable only if page total stays under target. |
| Triage | 290 | Warnings by Category (30d) | 2097ms | Keep, but monitor in Device Work Queue page timing. |

# Navigation Map

| Final dashboard | Current source | Function |
|---|---|---|
| Command Center | Patch Command Center plus selected Overall cards | All-client landing page. Shows where attention is needed across clients. |
| Client Patch Review | Client Patch Status | One-client review and action planning. Top status band requires one selected client. |
| Device Work Queue | Triage plus selected Device Patching Status cards | Devices a tech should work next. |
| Device Detail | Device Drilldown | One-device evidence page. |
| Patch Evidence | Patch Detail (Filterable) | KB, patch, severity, and install-outcome lookup. |
| Patch Trends | Patch Trends | Time movement and reporting, after slow cards are addressed. |
| Activity Search | One Utilities dashboard | Raw activity/message search. |

# Command Center

| Current card | Card ID | Baseline | Verdict | Target title / note |
|---|---:|---:|---|---|
| Total Devices | 275 | 136ms | Keep/rename | `Fleet Approved Windows Devices` if object remains unclear. |
| Active Devices | 194 | 132ms | Keep/rename | `Fleet Active Windows Devices`. |
| Patching Devices | 195 | 115ms | Keep | `Included Devices` or `Fleet Included Devices` depending final layout. |
| Stalled Devices | 196 | 127ms | Keep | Clear enough in fleet device band. |
| Never-Patched Devices | 197 | 157ms | Keep | Clear enough in fleet device band. |
| Actively patching % | 265 | 235ms | Keep/rename | `Included Devices Actively Patching`. |
| Approved Patches | 198 | 314ms | Keep/rename | `Approved Patches`. |
| Manual Approval | 199 | 115ms | Keep/rename | `Patches Awaiting Manual Approval`. |
| Delayed Patches | 200 | 158ms | Keep | `Delayed Patches`. |
| Failed Patches | 201 | 154ms | Keep/rename | `Patch Failures`. |
| OS Patch Warnings (24h) | 300 | 132ms | Keep | Fleet warning signal. |
| OS Patch Failures (24h) | 301 | 135ms | Keep | Fleet failure signal. |
| Data Freshness | 302 | 137ms | Keep | Rename only if needed. |
| Clients Needing Attention | 202 | 280ms | Keep | Core landing card. |
| Failed Patch Queue | 203 | 206ms | Keep summary / link | Detailed work belongs in `Device Work Queue`. |
| Manual and Delayed Patches | 204 | 184ms | Keep summary / link | Detailed work belongs in `Device Work Queue`. |
| Patches Installed Awaiting Reboot | 205 | 308ms | Keep summary / link | Answers "servers patching/rebooting" when filtered. |
| Recent Patch Activity (Fleet) | 206 | 263ms | Keep | Good current-vibe signal. |
| Ingest Pipeline Status | 303 | 180ms | Keep | Needed to trust the dashboard. |

# Overall Patching Status

Verdict: merge and remove from primary navigation.

| Current card | Card ID | Baseline | Verdict | Target |
|---|---:|---:|---|---|
| Actively patching % | 207 | 183ms | Drop duplicate | Command Center already has this concept. |
| Fully patched % | 266 | 2130ms | Drop or rewrite | Too slow and overlaps client review/trends. |
| Actively patching | 271 | 161ms | Drop duplicate | Command Center. |
| Fully patched | 272 | 1588ms | Drop or rewrite | Not useful enough as a landing scalar. |
| Total Devices | 276 | 171ms | Drop duplicate | Command Center. |
| Active Devices | 209 | 107ms | Drop duplicate | Command Center. |
| Data Freshness | 208 | 166ms | Drop duplicate | Command Center. |
| Warnings (30d) | 307 | 161ms | Drop duplicate | Command Center / Device Work Queue. |
| Failures (30d) | 308 | 131ms | Drop duplicate | Command Center / Device Work Queue. |
| Patch count cards | 210-213 | <210ms | Drop duplicate | Command Center. |
| Patching status cards | 214-216 | <175ms | Drop duplicate | Command Center. |
| Current Patch State | 217 | 172ms | Move if useful | Patch Evidence. |
| Client compliance tables | 218-219 | 2361-6368ms | Replace | Command Center client ranking, optimized. |
| Devices Needing Reboot | 220 | 178ms | Move | Device Work Queue; summary link from Command Center. |
| Ingest Status | 221 | 211ms | Drop duplicate | Command Center. |

# Client Patch Review

| Current card | Card ID | Baseline | Verdict | Target title / note |
|---|---:|---:|---|---|
| Approved Windows Devices | 277 | 144ms | Keep | Shows client device scope only when one client selected. |
| Active Windows Devices | 222 | 112ms | Keep | Client scoped. |
| Client Status | 223 | 136ms | Keep | Guarded: only meaningful with one client selected. |
| Included Devices | 267 | 148ms | Keep | Answers enabled-for-patching for selected client. |
| Devices Scanned Successfully | 273 | 122ms | Keep | Client scan coverage. |
| Devices Installed Recently | 274 | 119ms | Keep | Client recent install activity. |
| Devices Needing Action | 278 | 178ms | Keep | Click into client-scoped Device Work Queue. |
| Patch count cards | 224-227 | <275ms | Keep/rename | Use patch-object titles. |
| Device status cards | 228-230 | <185ms | Keep | Client device status band. |
| Current Patch State | 231 | 195ms | Keep | Client evidence. |
| Device Type / OS breakdown | 232-233 | 1697-1824ms | Keep only if still useful | Watch page-load target. |
| Failed Patch Queue | 234 | 302ms | Keep | Client-scoped work list. |
| Manual and Delayed Patches | 235 | 157ms | Keep | Client-scoped work list. |
| Warnings / Failures | 294-295 | <185ms | Keep | Client-scoped issue signals. |
| Top Problem Devices | 309 | 208ms | Keep | Client-scoped action bridge. |
| Devices Needing Reboot | 236 | 155ms | Keep | Client-scoped reboot list. |

# Device Work Queue

Current source: `Triage`.

| Current card | Card ID | Baseline | Verdict | Target title / note |
|---|---:|---:|---|---|
| Total Issues | 280 | 198ms | Keep/rename | `Devices Needing Action` or `Open Device Issues`. |
| Never Patched | 281 | 207ms | Keep | Action bucket. |
| Stalled | 282 | 236ms | Keep | Action bucket. |
| Offline | 283 | 263ms | Keep | Action bucket. |
| Failed Installs | 284 | 186ms | Keep | Action bucket. |
| Reboot Pending | 285 | 155ms | Keep | Action bucket. |
| With Warnings | 304 | 158ms | Keep | Action bucket. |
| With Failures | 305 | 190ms | Keep | Action bucket. |
| Triage Queue | 286 | 460ms | Keep/rename | `Device Work Queue`. |
| Issues by Client | 287 | 214ms | Keep | Helps choose client work. |
| Issues by Type | 288 | 171ms | Keep | Helps choose issue class. |
| Scan Gaps | 456 | 200ms | Keep | Work list. |
| Reboot Blockers | 457 | 220ms | Keep | Work list. |
| Approval Backlog | 458 | 219ms | Keep | Work list. |
| Stalled or Never Patched | 459 | 263ms | Keep | Work list. |
| Warnings by Category | 290 | 2097ms | Keep/watch | Needed for repeated-warning search. |
| Top Devices by Warnings | 296 | 315ms | Keep | Work list. |
| Top Devices by Failures | 297 | 171ms | Keep | Work list. |
| Failures by Error Code | 291 | 558ms | Keep | Repeated-error search entry. |
| Devices Matching Warning Category | 310 | 214ms | Keep | Filtered result table. |
| Devices Matching Failure Error Type | 311 | 196ms | Keep | Filtered result table. |

# Device Patching Status

Verdict: remove from primary navigation.

| Current card | Card ID | Baseline | Verdict | Target |
|---|---:|---:|---|---|
| Active Devices | 251 | 119ms | Drop duplicate | Command Center / Client Patch Review. |
| Patching Devices | 252 | 128ms | Drop duplicate | Command Center / Client Patch Review. |
| Stalled Devices | 253 | 141ms | Drop duplicate | Device Work Queue. |
| Never-Patched Devices | 254 | 155ms | Drop duplicate | Device Work Queue. |
| Patching Status | 255 | 127ms | Move if useful | Command Center summary only. |
| Device Type / OS / Organization breakdowns | 256-258 | <185ms | Move only if useful | Command Center or Client Patch Review. |
| Problem Devices - Triage Queue | 279 | 471ms | Drop duplicate | Device Work Queue already owns this. |
| All Devices by Patching Status | 259 | 11183ms | Remove/replace | Use Device Work Queue filtered lists instead. |
| Patch Count Source Check | 289 | 191ms | Demote | Support/debug only, not primary nav. |

# Device Detail

| Current card | Card ID | Baseline | Verdict | Note |
|---|---:|---:|---|---|
| Device Summary | 245 | 13984ms | Keep but optimize/guard | Must not load expensive unselected-device data. |
| Current Patch State | 246 | 157ms | Keep | One-device evidence. |
| Install Results Over Time | 247 | 492ms | Keep | One-device trend. |
| Recent Patch & Reboot Activity | 248 | 264ms | Keep | One-device activity. |
| Patch State History | 249 | 968ms | Keep/watch | One-device history. |
| Install History | 250 | 1114ms | Keep/watch | One-device history. |
| Warnings / Failures | 292-293 | <230ms | Keep | Full error evidence. |

# Patch Evidence

| Current card | Card ID | Baseline | Verdict | Note |
|---|---:|---:|---|---|
| Current Patch State | 237 | 199ms | Keep/rename | Patch state, not device status. |
| Severity Breakdown | 238 | 151ms | Keep | Patch severity lookup. |
| Devices by Patch Count | 239 | 168ms | Keep | Patch-to-device evidence. |
| KBs by Patch Count | 240 | 170ms | Keep | KB lookup. |
| Install Results Over Time | 241 | 268ms | Keep | Patch install evidence. |
| All Devices by Patch Count | 242 | 284ms | Keep | Evidence table. |
| All KBs by Count | 243 | 259ms | Keep | Evidence table. |
| Total matching patch rows | 446 | 200ms | Keep | Search result count. |
| Patch Detail Table | 244 | 266ms | Keep | Filterable evidence table. |
| Patches by Type | 306 | 200ms | Keep | Patch type breakdown. |

# Patch Trends

| Current card | Card ID | Baseline | Verdict | Note |
|---|---:|---:|---|---|
| Patch Installs per Day | 260 | 354ms | Keep | Core trend. |
| Failed Install Attempts per Day | 261 | 165ms | Keep | Core trend. |
| System Reboots per Day | 262 | 1587ms | Keep/watch | Needed for patch/reboot reporting. |
| Active Devices Seen per Day | 263 | 6621ms | Optimize or defer | Too slow for first view as-is. |
| Fully patched % per Day | 268 | >15000ms | Must optimize | Cannot remain in primary nav as-is. |
| Patching Devices per Day | 269 | 331ms | Keep | Core trend. |
| Currently-MANUAL Patches by Age | 264 | 311ms | Keep | Backlog age trend. |
| OS Patch Warnings per Day | 298 | 162ms | Keep | Warning trend. |
| OS Patch Operational Failures per Day | 299 | 136ms | Keep | Failure trend. |

# Activity Search

| Current card | Card ID | Baseline | Verdict | Note |
|---|---:|---:|---|---|
| Activity Search | 454 | 286ms | Keep one copy | Rename dashboard to `Activity Search`; remove duplicate Utilities dashboard from primary navigation. |

# Implementation Notes

- Update `_DASHBOARD_LEGACY_NAMES` before renaming dashboards so live
  dashboard IDs are preserved.
- Keep card UID descriptions intact so card IDs survive dashboard
  renames.
- Preserve cross-dashboard filter propagation for all click-throughs.
- Do not implement slow cards unchanged just because their old dashboard
  existed.
- After implementation, repeat:
  - broad no-filter dashboard timing;
  - filtered timing for `Command Center`, `Client Patch Review`, and
    `Device Work Queue`;
  - click-through filter carryover validation.
