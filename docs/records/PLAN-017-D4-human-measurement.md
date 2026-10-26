# PLAN-017 — D4 private human measurement procedure

**SUPERSEDED for part C by user direction / Claude round 19, Point 38.**
Claude performs C in a new session using reviewed minimal metrics-only commands.
This retained human procedure is historical; do not assign its browser/CSV steps
to the user. Current execution authority is in the diagnostic document and root
blueprint. No production measurements are recorded here.


2026-10-25. For execution only after explicit **C** approval and D1/SQL
preconditions. Proposed executor: **`chamayer`, the workspace user**. This
document contains instructions, not a record of execution. The
[exact D4 scope](PLAN-017-diagnostic-queries.md#d4--runtime-role-query-and-full-request-timings)
and [approval request](PLAN-017-approval-request-draft.md) remain controlling.

## Private setup and session

Use your own private browser on the authorized Operations deployment and tenant.
Use an existing authenticated session; if unavailable, C explicitly includes
one manual login with your existing account and normal MFA, authentication
POST(s), session creation/update and normal auth/access bookkeeping. Stop on
failed authentication. Never give an agent credentials, MFA, cookies, screenshots,
HAR/network exports, customer URLs, bodies or CSVs. No agent-operated browser,
helper or terminal captures these measurements.

Open browser DevTools **Network**. Enable **Disable cache**, which applies while
DevTools remains open. Leave network/CPU throttling off. Do not clear server
caches or restart services. Record cache condition as `browser-disabled;
server-unknown` and whether this is the first or repeated request. Browser cache
settings do not establish a cold application/database cache. Clear only the
Network panel's request list between measured navigations; do not clear cookies.

Arrange a private download directory outside the repository and any directory
visible to an agent. Downloaded CSVs are temporary sensitive files. Use the
local CSV-count procedure below, then delete each file. Do not open it in a
spreadsheet, upload it, or copy its filename/path/contents into the return table.
Browser session/cache artifacts remain private; export none as evidence.

## Reading metrics and executing requests

After SQL preflight/plan checks pass, run the 15 public route shapes below in
the numbered order, one request at a time. Navigation/normal assets may load
normally; measure the main **document** request (or CSV response) only. Avoid
clicking other links, customer/source links or filters. No client-filter probes.
The two unfiltered inventory HTML routes may each be repeated twice immediately
after the first load, still sequentially, making at most 19 measured requests.

In Network, select the document/CSV response and read:

- **Status**: numeric HTTP status. Redirect to login or an error stops the batch;
  do not paste response text. Record failure category only.
- **Transferred bytes / resource bytes**: use the request's Size/Transferred
  fields or their tooltip. Transferred size includes transport overhead as
  reported by the browser; resource size describes the response resource. Use
  bytes, converting displayed KiB/MiB with 1,024/1,048,576. Mark unavailable
  fields `unknown`, never substitute the Network panel's all-assets totals.
- **TTFB milliseconds**: Timing panel's **Waiting for server response (TTFB)**
  phase. Record the browser's reported definition, not a claimed server-only
  execution duration.
- **Finish milliseconds**: request start to response download completion
  (the request's total Duration/Time), including queue/connect/transfer as
  reported. Do not use the page-wide Finish/DOMContentLoaded/Load footer, which
  includes other resources. This is not a measure of completed browser rendering.

Record only visible numeric population/card/table totals needed for parity and
a parity flag. Never record labels, clients, names, IDs or row content. If a
metric is unavailable, use `unknown`; do not add instrumentation. Assets and
Python/render/database costs are not separately attributed by these metrics.

HTML must complete within 15 seconds and both measured response sizes must be
<=8 MiB; CSV within 30 seconds, both sizes <=32 MiB and <=50,000 complete data
records. Monitor the request; abort navigation/download on an observed breach,
stop the batch, and report the limit flag. Manual observation/abort is not a
hard byte/time enforcement mechanism and cannot guarantee server cancellation.
Do not retry while completion is unknown. Total diagnostic wall budget after
authentication is ten minutes; skip remaining routes when exhausted.

Run CSVs only after the corresponding D4.1 population is known <=50,000 and
SQL/plain-plan review permits them. **Computers CSV, row 15, runs last only if:**

1. D4.1 current_computers <=50,000;
2. every preceding measured HTML load, including all repetitions, finished in
   **strictly less than 5,000 ms**;
3. all SQL probes passed plan review and their time limits, and every preceding
   measured response completed without error or any byte/time/row-limit breach;
4. all required metrics are known and at least 30 seconds remain in the
   ten-minute diagnostic budget.

Otherwise mark row 15 `skipped`. These are conservative eligibility thresholds,
not proof a complete-detail CSV is cheap or authorization to exceed its caps.
The compact HTML path differs from the CSV query. A population of 50,001, an
HTML duration of exactly 5,000 ms or a missing duration fails the gate.

## Private CSV record count and deletion

Wait for a **complete** download with successful status and within caps. A
partial download is never complete validation. In a separate local PowerShell
window that is not shared with any agent, run the following. Enter only the
exact temporary CSV file's absolute path; verify it points to that one download
outside the repository. This uses Python's CSV parser so quoted fields with
embedded newlines do not inflate a line count. The header is excluded.

```powershell
$measurementCsv = Read-Host 'Absolute path of this one private temporary CSV'
if (-not [IO.Path]::IsPathRooted($measurementCsv) -or
    [IO.Path]::GetExtension($measurementCsv) -ne '.csv' -or
    -not (Test-Path -LiteralPath $measurementCsv -PathType Leaf)) {
    throw 'Stop: expected one existing absolute CSV file path'
}
try {
    @'
import csv
import sys
with open(sys.argv[1], encoding="utf-8-sig", newline="") as stream:
    records = csv.reader(stream, strict=True)
    header = next(records, None)
    if header is None:
        raise ValueError("No CSV header; count unverified")
    print(sum(1 for _ in records))
'@ | python - $measurementCsv
} finally {
    Remove-Item -LiteralPath $measurementCsv
    Remove-Variable measurementCsv
}
```

Only the successful numeric result belongs in the table. On a count/parser
failure mark `unknown`, not zero; return no traceback. Confirm the one downloaded
file was deleted; if deletion failed, remove that exact file privately before
reporting completion. Cancel/delete any partial download too. No recursive
deletion, unrelated file cleanup or repository write is authorized. If Python
or the required metrics are unavailable, mark the relevant check unverified.

## Metrics-only return table

Return **only this table**, with numbers or the fixed flags shown below. Leave
unavailable cells `unknown`; use `skipped` when a gate prevents execution. Route
shapes here are public paths, never replace them with a host, client or source
URL. For repetitions add only `1a/1b` and `6a/6b`, using the same public shape.
Do not attach files, screenshots, HAR, logs or authentication information.

Session header: tenant=`1`; DB role=`operations_app` (confirmed/unknown);
cache=`browser-disabled; server-unknown`; capture UTC=`____`;
D4.1 Computers=`____`; D4.1 source records=`____`; all SQL preconditions=`pass/fail/unknown`.

| # | Public route shape | Status | Transferred bytes | Resource bytes | TTFB ms | Finish ms | Numeric displayed total | Complete CSV data records | Complete/limit/skipped/unknown | Parity pass/fail/unknown | CSV deleted yes/no/n/a |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | /inventory/computers/ | | | | | | | n/a | | | n/a |
| 2 | /inventory/computers/?platform=Ninja | | | | | | | n/a | | | n/a |
| 3 | /inventory/computers/?computer_scope=any_online | | | | | | | n/a | | | n/a |
| 4 | /inventory/computers/?computer_scope=missing_required | | | | | | | n/a | | | n/a |
| 5 | /inventory/computers/?page=2 | | | | | | | n/a | | | n/a |
| 6 | /inventory/source-records/ | | | | | | | n/a | | | n/a |
| 7 | /inventory/source-records/?state=active | | | | | | | n/a | | | n/a |
| 8 | /inventory/source-records/?relationship=attached_computer | | | | | | | n/a | | | n/a |
| 9 | /inventory/source-records/?page=2 | | | | | | | n/a | | | n/a |
| 10 | /inventory/source-records/?format=csv | | | | | | | | | | |
| 11 | /inventory/clients/ | | | | | | | n/a | | | n/a |
| 12 | /patching/ | | | | | | | n/a | | | n/a |
| 13 | /software/ | | | | | | | n/a | | | n/a |
| 14 | /admin/jobs/ | | | | | | | n/a | | | n/a |
| 15 | /inventory/computers/?format=csv | | | | | | | | | | |

Parity remains `unknown` unless matching numeric totals/scopes can actually be
checked privately. No selected metric or first-page result proves all-filter,
all-client or export parity. An error may be reported with a fixed category
`auth`, `http`, `timeout`, `size`, `row-cap`, `count`, `delete` or `unknown`,
never raw response text.
