# PLAN-056 — Post-release acceptance

## Status and authority

Prepared 2026-11-11 after reconciling local HEAD `ae45b463` / 0.144.11 with
the release handoff and Git diff. The prior release record owns deployment
evidence; Stage A results are recorded below. This protocol supersedes older
measurement proposals only for the post-release checks below. PLAN-056 remains
active and the original assessment checklist remains open.

Stage A approved and completed on 2026-11-11. Stages B/C
define acceptance and preparation gates, not executable approval requests.
Preserve all excluded working changes; validate installed release code only.

## Stage A — Home and Coverage first/repeat

Purpose: establish whether both fixed pages complete and measure actual HTTP
responses before considering further remedies. Use the existing configured-admin
normal login/logout path, internal container loopback, and live worker pool.
Normal session creation/deletion, last-login and access-log effects are included
in the requested authorization. Do not create accounts or synthetic sessions.

Artifacts: `scripts/diagnostics/plan056_release_pages.py`, existing
`plan056_http_pilot.py`, and `plan056_matrix_completion.sh`. The new collector
contains four measured GETs maximum: Home `/` first/repeat, then Coverage
`/inventory/computers/` first/repeat, sequentially. Each request has a 20-second
whole-response deadline. Repeat follows only a complete HTTP 200. Stop at first
error/redirect/deadline; do not retry or issue the next page. Authentication
uses the helper's existing 20-second socket limits; wrap the whole collector
in `timeout 180`. Never emit credentials, cookies, HTML or exception messages.

Before execution, read `docs/operations.md` and inspect the shared helper's
machine-local SSH capability without printing secrets. Use
`..\Scripts\Invoke-DevTool.ps1` for remote commands and the same approved SSH
target for SCP. Create one fresh `/tmp/plan056-release-acceptance.XXXXXX` host
directory; transfer only the three named files, verify SHA-256, and refuse any
existing destination. Copy the two Python files into one fresh container
directory with the same naming pattern; invoke the collector by its `.py` path.
The sibling import resolves the authentication helper. No application-file copy,
entrypoint, migration, inline Python, cache flush or service restart.

Preflight reads only service running/health fields and hashes of the released
`views.py` and `issue_selection.py` in Operations. Compare with committed blobs,
not working-tree files. Stop on mismatch/unhealthy service. Run one collector;
capture its redacted JSON locally. Use the completion script with its exact
32-hex prefix, after the pass. Require one matching status-200 completion marker
per successful measured request. If a request is incomplete, use at most two
completion reads separated by at most 60 seconds; finish within 70 seconds of
the failure. This bounds observation, not server execution. Missing completion
leaves server work unknown: stop and report; no cancellation is authorized.

Hash-check transferred copies, remove only those exact diagnostic files, remove
the empty directories, and verify absence. No recursive/wildcard cleanup.
Total external budget: ten minutes including preflight, authentication,
completion observation and cleanup; no polling/repeated pass to fill the budget.
If cleanup cannot complete, report exact remaining paths without broader removal.

Report UTC, route/role, status, header/full-response seconds, bytes and completion
markers. Home retains its inherited ordinary-response goal of <=1.5 seconds
and hard maximum <2 seconds, including cold navigation. Configured-admin results
are admin-only. Coverage has no adopted numerical SLO: successful completion
within this diagnostic limit is evidence, not a new SLO or full acceptance.
Do not replay the original slow join. Body content/parity is not certified by
status or byte count. First/repeat does not prove a cold worker or a cache hit.

## Stage B — Controlled cold Home

Only after reviewing Stage A, prepare the exact collector/process ownership and
cleanup artifacts described in the retained
[cold-navigation proposal](PLAN-056-cold-navigation-protocol.md). Review installed
login/cache behavior again before proposing a fresh temporary one-worker server.
Seek separate authorization for that process and its termination. Maximum two
Home GETs, 20 seconds each, 120-second collector budget; database/OS buffers
remain uncontrolled. Prove the initial application-cache state before labeling
a result cold. Retain the Home target above even if the result fails it.
No such server or script is started by Stage A approval.

## Stage C — Scheduled background behavior and write effects

Prepare a separately reviewed, indexed, bounded read-only collector for recent
post-deployment matcher/ownership runs: at most 20 terminal summaries per family,
24-hour horizon, existing runtime role, tenant 1, 3/1/5-second statement/lock/idle
limits. Review actual catalog keys and query plans without ANALYZE first.
Record outcome, duration and existing scope/change metrics only. Mixed-release
runs and unknown scope cannot support before/after runtime claims.

For an active-work observation, retain the prior single current-Jobs gate and
one five-sample/60-second host/database window. No running relevant job means
stop without polling or forcing one. No local fleet/timing run. Permission gaps
remain gaps; do not grant privileges or enable instrumentation. Resource
interaction remains deferred; this is not a new page/Job concurrency campaign.

Success requires observed scheduled completion without a newly demonstrated
publication/queue correctness regression. Table-wide counter deltas cannot prove
per-job write savings. Matcher equality and history UPDATE suppression have
synthetic correctness evidence, but live write reduction remains unverified
unless existing per-run metrics or a separately approved representative rehearsal
can distinguish equal content from genuine changes. Do not invent a savings
threshold, force a Job, modify data, or query customer payloads to fill that gap.

Browser usability, external network, ordinary-user access, other pages/filters,
content parity, tail latency and full platform acceptance remain separately open.

## Local preparation validation

Collector compilation and Ruff lint/format checks pass. Plan registry and
`git diff --check` pass; root and detailed blueprints are below 4,000 characters.
Preparation changed no runtime files or tests. No commit, push or deploy.

## Stage A results — 2026-11-11

External window: 15:54:58–15:56:56 UTC, within the ten-minute budget.
All four services were running/healthy. Installed Operations `views.py` and
`issue_selection.py` hashes matched the committed `ae45b463` blobs:

| File | SHA-256 |
| --- | --- |
| views.py | `bd32ffdf15807dc68b806cf415d50cf345084eeefb76fa779c6481cd0ff2578c` |
| issue_selection.py | `8d148fd581a873848b40d3357d8c6761209a310b740d4f1fe28e6881dea9d385` |

The initial Docker health format lost its argument quoting and failed to return
health fields; a corrected format succeeded before authentication/page requests.
No unhealthy/mismatched service was observed. This was a metadata-command
correction, not an HTTP retry.

Normal configured-admin login succeeded. All requests used internal loopback and
the live worker pool; cache/worker identity was uncontrolled. Completion prefix:
`4cb263447ccc228603bc696d868080ea`; each numbered marker was found once with
status 200 by the first bounded completion read.

| Page | Request start UTC | Marker suffix | HTTP | Headers s | Full body s | Bytes |
| --- | --- | --- | --- | --- | --- | --- |
| Home first | 15:55:58.195728 | 1 | 200 | 8.253 | 8.253 | 36,381 |
| Home repeat | 15:56:06.449515 | 2 | 200 | 6.774 | 6.776 | 36,381 |
| Coverage first | 15:56:13.225367 | 3 | 200 | 7.191 | 7.191 | 427,537 |
| Coverage repeat | 15:56:20.416790 | 4 | 200 | 6.101 | 6.104 | 427,537 |

Collector exited 0 after exactly four measured GETs. Normal logout returned 302
with session-cookie removal confirmed at 15:56:26.762130 UTC. No response body
content was retained. No timeout, retry, cancellation or further page request.

Transferred diagnostic SHA-256 values matched locally, on the host and in the
container before execution, and again before cleanup:

| Artifact | SHA-256 |
| --- | --- |
| plan056_release_pages.py | `7ee4e1d5e82e3c27c8bbd880c5caf1d0df03887c37b25cd3759a299ea2af8269` |
| plan056_http_pilot.py | `626fc08b9ed3443d8cb01b967d57d5d3d86218b3704051e0c55d6f71a0c8b045` |
| plan056_matrix_completion.sh | `7f8284801e484755bef20d427901802edaf48fd5188999d89c7e8e4d11921db9` |

Exact file removal and empty-directory removal succeeded; absence of
`/tmp/plan056-release-acceptance.dWqQzT` on host and container was verified.
Bytecode writes were disabled for the collector. Redacted page/completion
captures remain outside Git in the local temporary evidence directory
`plan056-stage-a-a916ba8e45b74a8e91ee52320e0c30e7`.

Coverage now has two completed full-page observations, unlike the prior
120-second incomplete observation. This is not a controlled before/after
comparison or a new Coverage SLO. Home exceeds both its <=1.5-second ordinary
goal and <2-second hard maximum on both observations; its latency acceptance
fails. The Issues correction alone has not established Home recovery. No
component cost attribution or background-work correlation was collected here.
Cold navigation, content/security parity, browser/external-network timing and
background write effects remain unverified. Do not infer a cache hit from the
repeat or declare platform recovery. Next review the retained Home components
and choose a bounded attribution/fix proposal before further external execution.

## Home diagnosis prepared after Stage A

Local review confirms committed `views.home` calls the domain readers
sequentially, including Inventory, Issues, Patching and Software. Only Issues
changed in this release. Earlier Inventory elapsed 1.716 s; Patching and Software
each exceeded their own three-second statement limit in separate transactions.
Those are historical observations, not current cost shares; do not add them to
reconstruct the Stage A request. Installed code hashes must be rechecked.

The preserved Software candidate removes approval/risk fields and changes card
detail; it is not a behavior-preserving optimization. Preserved Home caching
still performs the same work on a miss and cannot alone establish the cold
target. Do not adopt either as the next fix without its own reviewed scope.

Prepared collector:
`scripts/diagnostics/plan056_home_release_components.py`, SHA-256
`ac558c1028de750288cb03e82d2b0596072f62ca9372fdc1706f9763ac752e93`.
It adapts the retained direct-reader diagnostic with committed-release hashes
for ten source modules, a longer bounded statement limit, an overall alarm and
per-component SQL-call count/execution-time metrics. All return values are
discarded. SQL text/parameters, result counts and customer data are not output.
SQL execution timing includes control statements but excludes fetch/conversion;
component elapsed includes reader work. No exact HTTP breakdown is claimed.

Proposed execution: one pass through the shared helper on the same production
host, existing Operations runtime role. Hash gates precede Django/database setup.
One tenant-1 repeatable-read/read-only transaction: policy, Clients, Computers,
Inventory, Issues, Patching, Coverage, Software, Sources and Jobs, each once in
Home order. Ten-second per-statement, one-second lock, five-second idle limits;
45-second process alarm; outer `timeout 55 docker exec ... python <path>.py`.
Stop on first error, source mismatch or unavailable reader; no retry/continuation.
No HTTP/auth/session, synthetic account, forced Job, instrumentation installation,
cache flush, application-file edit, migration, service change or backend cancel.
Direct reader timing does not establish HTTP/cold/ordinary-user acceptance.

Transfer only this collector into fresh absent host/container directories under
`/tmp/plan056-home-release.XXXXXX`, verify its hash before invocation and cleanup,
disable bytecode writes, invoke by `.py` path, and remove only the exact copy
and empty directories, verifying absence. Retain redacted output locally.
Five-minute external budget, including setup and cleanup. No additional
diagnostic file, privilege or query is an automatic fallback.

Local compilation and Ruff lint/format pass. Source hash manifest is derived
from committed blobs, never the mixed working tree. User subsequently approved
this single read-only Home diagnosis and exact temporary file transfer/cleanup
on 2026-11-11; the completed outcome follows. Remediation must follow the
resulting attribution; new runtime/test edits and release retain their gates.

## Home diagnosis outcome — 2026-11-11

One approved invocation through the shared helper. External setup/cleanup window
16:06:00–16:06:58 UTC, within the five-minute budget. All ten committed-source
hash gates passed. Existing runtime role, tenant 1, one read-only repeatable-read
transaction; own backend PID 428603. Measurement began 16:06:28.819258 UTC and
finished 16:06:34.593531 UTC with status 0 and connection closure confirmed.

| Component | Elapsed s | SQL execute s | SQL calls |
| --- | --- | --- | --- |
| Device policy | 0.026 | 0.014 | 1 |
| Clients | 0.018 | 0.014 | 1 |
| Computers | 0.108 | 0.106 | 5 |
| Inventory | 0.903 | 0.902 | 5 |
| Issues | 1.772 | 1.319 | 4 |
| Patching | 0.344 | 0.343 | 5 |
| Coverage | 0.109 | 0.109 | 4 |
| Software | 2.156 | 2.155 | 4 |
| Sources | 0.263 | 0.262 | 4 |
| Jobs | 0.071 | 0.070 | 5 |

Collector exit 0; no timeout, unavailable reader, failure or retry. All return
values discarded. No HTTP/auth/session, forced Job, data/schema/config change,
service action, alternate role or cancellation. Software, Issues and Inventory
are the three largest observed reader costs (4.831 s of 5.770 s rounded reader
total). This is a same-pass reader total, not a reconstruction of Stage A HTTP.
Cache state, workload and transaction context differ; no controlled before/after
benefit, component regression or exact HTTP share follows from these observations.

Software's 2.156 s is predominantly cursor execution. Issues has 1.319 s cursor
execution and about 0.453 s elsewhere in its reader; that difference includes
fetch/conversion and Python work, not proven Python computation alone. Query-node
attribution is still missing. Patching completed in 0.344 s; its old timeout
does not establish it as the current dominant bottleneck. Sources/Jobs are not
the dominant costs in this pass. The fresh Issues result remains too costly
for a <=1.5 s whole-page goal even after its released simplification.

Even removing either Software or Issues entirely leaves the other readers over
the page budget in this pass. A single isolated reader correction cannot be
promised as sufficient. Next remediation scope must account for Software,
Issues and Inventory together, retain current card contents and tenant/security
semantics, and leave enough budget for all other readers, context and rendering.
No per-reader target allocation is adopted without agreement. If request-time
query simplification cannot achieve the cold goal, review a summary-publication
design with explicit freshness/invalidation/failure contracts before implementing
it; merely adding process-local caching does not solve miss-path work.

Host/container collector hashes matched the approved SHA-256 before invocation
and again before exact removal. Empty-directory removal and absence of
`/tmp/plan056-home-release.5TvT6l` on host and container were verified at
16:06:58 UTC. The local transfer copy was hash-checked and removed. Redacted
JSON and path metadata remain outside Git in local temporary evidence directory
`plan056-home-release-e160cee898c94c1485119aba66d92532`.

Home full-page acceptance remains failed based on Stage A; this diagnosis is
attribution, not recovery. Implementation/test changes, release, cold/background
checks and further external queries retain their separate gates.

## Quick navigation pass — user requested 2026-11-11

Authorized directly by the request for load times across high-level navigation.
One configured-admin login/logout, internal loopback/live workers, one GET each
for 15 main/Inventory/Admin landing pages listed in `plan056_nav_pages.py`.
No filters, repeats, browser assets, body retention, actions or SQL observers.
Jobs refresh off. GET handlers reviewed locally; new Admin/Inventory entries
read/render only. Normal session/last-login/log effects follow the established
authentication path. Twenty-second whole-response limit; stop on first failure.
Outer collector limit 380 seconds. Ten-minute setup/execution/cleanup budget.
Use shared SSH helper, fresh absent host/container directories, exact reviewed
collector/auth helper/completion script transfers, SHA-256 checks before use and
cleanup, and bytecode writes disabled. Existing completion filter accepts all
15 exact markers. After failure, at most two completion reads within 70 seconds;
no retries or cancellation. Remove exact copies and empty directories; retain
redacted timing evidence outside Git. No runtime edits, deployment or data work.
Collector syntax and Ruff lint/format pass. Completed results follow.

### Navigation results

2026-11-11, external window 16:12:22–16:14:25 UTC. Exactly 15 sequential GETs;
all HTTP 200, all exact server-completion markers found once on the first read.
Collector exit 0; normal logout confirmed at 16:13:51.333211 UTC. No retries,
timeouts or additional measured requests. Marker prefix:
`169771384acb88d5266d4839d6c5071f`; suffixes follow navigation collector order.

| Page | Complete HTML seconds |
| --- | --- |
| Dashboard | 5.688 |
| Issues | 2.214 |
| Clients | 3.804 |
| Computers | 1.195 |
| Patching | 4.349 |
| Software | 13.094 |
| Inventory Clients | 5.793 |
| Inventory Computers / Coverage | 4.605 |
| Inventory Source records | 7.700 |
| Admin Overview | 1.355 |
| Admin Data | 1.238 |
| Admin Sources | 6.346 |
| Admin Jobs, refresh off | 1.105 |
| Admin Health | 1.902 |
| Admin Settings | 0.147 |

These are configured-admin internal-loopback HTML times, one observation per
page, with uncontrolled live-worker/cache state. They exclude assets, browser
rendering and external network/proxy costs. Body contents discarded. No new
page SLO, tail-latency estimate or controlled before/after comparison. Home still
fails its adopted target. The slowest pages prioritize summary-consumer review;
timings alone do not prove summary aggregation causes every page's delay.
Keep distinct populations/permissions/freshness before sharing a result.

Transfer SHA-256 values matched at local/host/container boundaries and again
before cleanup: collector `147aa514500efa86ad72a4791c65dd3347f567e797f6a13ceefbe9f2e6e83eba`;
authentication/completion helpers retain the hashes recorded for Stage A.
Exact host/container files removed; empty directory removal and absence of
`/tmp/plan056-nav.ZWGpKe` verified at 16:14:25 UTC. Local redacted JSON includes
per-request UTC, route, marker, status, header/body time and bytes; captures are
outside Git in `plan056-nav-604cfbc98d63416497a8847ab17d8b7d`.
No runtime/test changes, business writes, forced Jobs, deployment or migration.

### Worklist authority — 2026-11-11

User directed that all 15 measured navigation pages become fixed numbered items
and that work stay on the list until settled. The active PLAN-056 handoff owns
that list, numbered in descending baseline-time order, starting with Software.
All 15 remain open, including faster pages. Settlement requires an evidence-backed
disposition accepted by the user; retain per-item decisions and validation here.
Shared work must identify every affected item; no implicit closure or renumbering.
This list is separate from the original 12-item platform assessment checklist.

## Item 1 — Software query breakdown

User requested the breakdown directly. One default `_software_page_data` call
on installed ae45b463 through the shared SSH helper, existing runtime role,
tenant 1, repeatable-read/read-only. No authentication, sessions, HTTP, rendering,
Jobs, writes, role changes or EXPLAIN. Default empty GET parameters and overview
resolver name select the ordinary overview code path; no user is impersonated.
Ten-second statement, one-second lock, five-second idle limits, 45-second alarm,
outer `timeout 55`; five-minute external setup/execution/cleanup budget.
Stop on first SQL error, source mismatch or deadline even if reader code would
swallow the error. No retries. Six source-file hash gates before database access.
Emit query time and code call site, never SQL/parameters/result values. Discard
the context dictionary. Query timing excludes fetch/conversion and is not an
exact decomposition of the earlier HTTP observation.

Artifact: `scripts/diagnostics/plan056_software_breakdown.py`, SHA-256
`1ef06c2c432581d6a02a5d330110ca9224c86f1215fd87e29a835dc4872863b7`.
Compilation and Ruff lint/format pass. Transfer only this file into fresh absent
host/container directories under `/tmp/plan056-software.XXXXXX`, verify hashes
before execution and cleanup, disable bytecode writes, invoke by `.py` path,
remove the exact copies and empty directories, verify absence. Retain redacted
output outside Git. Completed outcome follows; item 1 remains open.

### Item 1 measured breakdown — 2026-11-11

One invocation, all six source gates passed. External window 16:26:24–16:27:41
UTC. Reader ran 16:26:54.030573–16:27:04.463843 UTC; elapsed 10.433 s,
17 emitted SELECT/WITH execution timings totaling 10.355 s. Exit/status 0,
connection closure confirmed. No timeout, error, retry or unavailable-layer
fallback was reported. No HTTP, session, render, background Job or business write.

| Work | Seconds | Release code location |
| --- | --- | --- |
| Approval/review status counts | 3.920 | views.py:6538 |
| Current-title rollup / installation and product totals | 2.646 | views.py:6235 |
| Fleet risk distribution | 1.509 | views.py:6020 |
| Capability-categorized title count | 0.799 | views.py:6064 |
| Preferred software display names | 0.618 | software_display.py:24 |
| Active Software issue count | 0.352 | views.py:6507 |
| Publishers awaiting decision | 0.259 | views.py:6476 |
| Distinct decision-prompt titles | 0.142 | views.py:6528 |
| Seven-day product count | 0.042 | views.py:6407 |
| Top new product | 0.029 | views.py:6422 |
| New high-risk product count | 0.020 | views.py:6446 |
| Recent installations | 0.010 | views.py:6362 |
| Classifier configuration | 0.006 | views.py:6546 |
| Three availability probes, combined | 0.003 | views.py:5946,5962,5974 |
| Decision-prompt type lookup | 0.001 | views.py:6515 |

Labels were mapped against committed release source, not mixed-worktree line
numbers. Individual rounded query times sum to 10.356 s; unrounded collector sum
is 10.355 s. About 0.078 s remains outside emitted query executions, including
fetch/conversion, Python, transaction control and unclassified execution.
The exposure-count statement starts with a SQL comment and was not emitted by
the SELECT/WITH prefix filter; its execution is included in that remainder,
not separately timed. Do not claim every SELECT was individually emitted or
attribute the remainder entirely to Python.

The three largest queries total 8.075 s, about 77% of this reader pass. The
first two both rebuild title-level results from live installations under current
Computer scope. This supports prioritizing Software-owned publication for those
summaries; no statement-node root cause or index conclusion was established.
This is a separate direct-reader observation, not a decomposition of the earlier
13.094-second HTTP request; navigation, authentication and rendering are excluded.

Transfer hashes matched before execution and again before cleanup. Exact
host/container copies removed, empty directories removed, and absence of
`/tmp/plan056-software.U4OgJT` verified at 16:27:41 UTC. Local transfer copy
hash-checked/removed. Redacted JSON retained outside Git in
`plan056-software-b7f16f221ea947df8a8d3b2b4ee5de0a`.
No runtime/test/schema change, commit or deployment. Item 1 remains open.

### Item 1 contract preparation — 2026-11-11

User requested the Software contract. Drafted
[ADR-0058](../../operations/docs/decisions/0058-software-summary-publication-contract.md)
from existing design/accepted Software decisions and committed reader semantics.
It records per-metric populations, producer/dependency/publication boundaries,
live decisions and expiry, proposed freshness/performance, failure/rebuild,
tenant/client protections and required enforcement/acceptance. ADR-0039 remains
Proposed; title-status labeling and implementation mechanism reviews are explicit.
DESIGN and documentation index link to the proposal. Handoff/root/module routing
and registry point to contract review under item 1; all 15 items remain open.

Local links, fixed numbering/open-state check, plan-registry validation and
`git diff --check` pass. All three handoffs remain within 4,000 characters.
Documentation-only preparation; no new runtime/test/schema edits or external
execution. No runtime performance, refresh feasibility or new enforcement is
claimed. The user subsequently accepted ADR-0058 on 2026-11-11, including its
freshness/latency targets and accurate title-status labeling. Contract approval
does not authorize implementation. Next prepare the concrete publication design,
update hooks, migration/rebuild and validation plan; preserve excluded work.

### Software implementation step 1 — local reader separation

2026-11-11: user authorized step 1 of the fixed six-step implementation worklist
with “go.” This supersedes the prior runtime-edit gate only for this scoped
reader separation. Schema, test-file edits, external execution, commit, push and
deployment remain unapproved.

`views.py` now routes Software overview HTML to `_software_overview_data`.
Products and both existing CSV routes retain `_software_page_data`. Existing
status/findings/window/workflow, risk, capability-count and recent-detail reads
were extracted into shared helpers. The overview calculates its current-Computer
totals directly and no longer invokes the Products filtering/pagination CTE.
Existing query semantics and failure fallbacks are retained for this preparation
step; publication, freshness/failure changes and accurate status copy remain
later worklist steps. No speculative SQL or coordination design was used.

Local validation:

- Python compilation and Django system checks (`config.settings.base`) passed.
- Nineteen existing focused Software review tests passed; five unrelated
  PostgreSQL-dependent Home cases were deselected. No test files were edited.
- Sixty-four mocked before/after request comparisons passed: overview and
  Products HTML plus both CSV routes; populated/empty results; available/missing
  safety/capability relations; default and combined filter/sort/page requests.
  Rendered HTML/CSV and headers matched. Products/CSV normalized SQL and parameter
  sequences matched the pre-edit working source. Overview requests did not run
  the Products CTE. This is synthetic parity, not PostgreSQL or live HTTP proof.
- AST comparison confirmed preexisting functions/classes outside the two
  intentionally changed Software functions were unchanged. Existing unrelated
  working edits were preserved.
- Ruff reported 96 findings in both the pre-edit snapshot and current full file;
  no new function/rule findings were introduced. Whole-file Ruff is not clean.
- `operations/Dockerfile` already includes `apps/`; no new runtime file,
  dependency, entrypoint, port, schema or packaging change was needed.
- Plan-registry validation and `git diff --check` passed. Active handoff size
  limits and updated local documentation links were checked before handoff.

The first request-smoke attempt encountered the workstation SQLite schema while
rendering a registry-backed label; the successful comparison isolated that label
lookup with synthetic names. No database repair or migration was attempted.

Step 1's reader boundary is complete locally. The overview still uses live
aggregates until steps 2–5 provide a valid publication. No timing benchmark,
database-backed parity, external request or production validation was performed.
All 15 navigation items, including Software, remain open.

### Software implementation step 2 — local aggregate storage and producer

2026-11-11: user directed “DO 2.” Implemented only the required aggregate store
and callable Software owner. No signals/scheduling, page cutover, broader
coordination system, commit, push or release was added.

- New migration `0407_software_overview_aggregate` follows tracked migration
  0406 without editing it. It creates one tenant-keyed aggregate table, a
  security-barrier read view, and `refresh_software_overview(bigint)` as sole
  runtime writer. There is no startup population/backfill. Required catalog and
  exposure SELECT grants go only to the migration/definer role; reversal retains
  them to avoid removing preexisting grants or breaking other migrations.
  Applying 0407 requires the existing catalog (074/076/093) and effective
  exposure (114) ingest schema plus Django 0406; these dependencies are explicit
  prerequisites, not optional relations skipped during startup.
- `ingest/inventory/software.py::refresh_overview_read_model` calls that writer
  in the existing transaction helper. It is deliberately not invoked from
  inventory/classifier/page paths yet; existing refresh behavior is unchanged.
- The producer computes M01–M11 with the shared current-Computer population's
  frozen predicate, exact canonical grouping, modal publishers, existing
  status precedence, effective capabilities, safety membership, independent
  finding/prompt/exposure populations and seven-day windows. Missing safety
  does not become clean/unknown. Preferred top-product labels retain stale
  source spelling. SQL NULL and JSON null remain distinct prompt groups.
- Computation replaces one complete aggregate row. Published/observed/window
  and exposure-deadline metadata are stored. Input completion watermarks are
  explicitly empty and `contract_ready=false`; runtime cannot read this row
  until later steps implement and certify the remaining contract mechanisms.

Validation performed on small synthetic data only:

- Applied forward SQL and exercised the actual function in one temporary,
  network-isolated PostgreSQL 16 container. Checked all aggregate outputs with
  retired/deleted/pending-cleanup Computers, stale/deleted installations,
  wrong-tenant linkage, case-distinct titles, publisher mode/global versus
  device decisions, missing safety, distinct prompt JSON/NULL values, findings
  outside installed populations, bounded highlight labels and exposure counts.
- Checked repeated and empty refreshes, lifecycle transitions and restoration,
  prior-result preservation after a missing dependency, runtime DML/function
  denial, missing/wrong tenant rejection, forced RLS and uncertified read
  withholding. Reverse SQL removed only the new derived objects.
  The final privilege check used input ownership matching the documented role
  split, without blanket SELECT grants to the definer, and passed.
- Temporary PostgreSQL container and anonymous volume were removed. The
  development stack and its databases were not migrated or rebuilt.
- Python compilation, Ruff lint on both changed Python files, new migration
  formatting, Django system checks and migration-graph/dependency checks passed.
  Frozen title-status SQL matched the compatibility constants. The two existing
  inventory read-model tests and 19 focused Operations Software tests passed.
  The inventory test initially lacked required local configuration; it passed
  with inert synthetic settings. No real source/DB credentials were needed.
- Whole-file formatting for `ingest/inventory/software.py` retains two existing
  unrelated formatting differences at earlier lines; the appended entry point
  is formatted. Those existing lines were preserved. No test files were edited.
- Existing Dockerfile directory copies include the producer and migration;
  no dependency, port, entrypoint or Compose change was needed.
- Plan-registry, whitespace and updated local-link checks passed; all active
  handoffs remain below 4,000 characters.

This validates the local component, not full PostgreSQL-stack integration,
upstream-completion consistency, Jobs fencing, freshness throughput, live
decision cutover or HTTP latency. Those remain the later steps and their
authorization gates. No migration was applied to development-stack or production
databases. All 15 navigation items remain open. Resume step 3 in a fresh session
using `operations/BLUEPRINT.md`; speculative designs remain set aside.

### Software implementation step 3 — local input and expiry connections

2026-11-11: user directed “next” after step 2, then directed continuation.
Implemented only the missing Software overview connections in the existing
Jobs framework. Steps 4–6 and item-1 acceptance remain open.

| Input family | Connection implemented or reused |
| --- | --- |
| Installation inventory and catalog relinking | Existing material-change edges to the classifier now reach `software-overview` after classifier success. |
| Computer lifecycle, association and ownership | Platform-evaluation and ownership Jobs have overview successors. Direct retirement/restoration, batch retirement, merge/split and identity actions request the overview after commit. |
| Capability/category evidence and rules | Existing catalog/intelligence classifier edges reach the overview; direct capability decisions now request it after commit, including earlier successful choices if a later selected choice is refused. |
| CVE/score/KEV, threat/EOL and safety inputs | Existing classifier successors cover classified output. Matcher success also requests the overview when match membership is unchanged but safety scores/signals changed. |
| Software findings and policy/settings | All three classifier variants have overview successors. Direct Software finding resolution/suppression and bulk suppression request it after commit. Existing policy/settings rebuild callbacks reach it through the classifier. |
| Title/publisher decisions | Existing full-classifier after-commit requests now lead to the overview; immediate next-read decision correctness remains step 5. |
| Exposure freshness and time passage | Unapplied migration 0408 exposes a protected deadline predicate. The existing minute scheduler requests the overview when stored seven-day or exposure deadlines expire. The allowed live recent-detail reader retains its 24-hour boundary. Missing publication does not start a timer bootstrap; owner completion requests the initial build. |

`shared/jobs_registry.py` defines one internal `software-overview` Job, with
the existing processing capacity and a tenant overview resource guard.
`ingest/operator_job_queue.py` dispatches it to step 2's Software-owned producer
and connects expiry admission. Operations callbacks use existing Jobs admission
and coalescing. No new queue, service, cadence, input log, receipt store, broad
trigger program, dependency or page cutover was introduced. The protected reader
still withholds `contract_ready=false` rows. Directory copies in the existing
Dockerfiles include every changed runtime file and the new migration.

Validation and limits:

- Focused existing checks: 18 Operations tests and 29 ingest tests passed;
  six tests failed on unchanged registry/workflow assertions. Replacing only
  the imported registry with the UTF-8-decoded HEAD source in memory reproduced
  five failing tests: fixed definition count, scheduled ownership successor,
  exact initial graph, universal resource assumption and exact identity-source
  graph. The new overview edge additionally invalidates the ninja-enrichment
  exact graph assertion and changes other exact graph expectations. This is
  not a clean test-suite result. Test-edit approval was requested but not given;
  no test files were edited in this step. Unrelated working test edits remain.
- Bounded local mock checks passed for the seven owner edges, no new schedule,
  expiry true/false admission, missing-function retry, generation result,
  propagated publication failure and enqueueing only through after-commit.
  Existing parametrized admission tests exercised all current workflow scopes.
- Actual 0408 forward SQL ran on one small synthetic PostgreSQL 16 fixture:
  missing row/future deadlines did not request refresh; each expired deadline
  did; missing/wrong tenant and application/readonly execution were denied;
  ingest raw DML was denied; reverse and reapply succeeded. The network-isolated
  temporary container and volume were removed. No service database was used.
- Django system checks, changed-module compilation and scoped Ruff lint passed.
  Queue/new-migration formatting passed. Registry formatting retains one
  preexisting resolver-layout difference; unrelated source was preserved.
  Views Ruff retained 96 findings; existing complexity counts increased, with
  no additional rule/function findings after normalizing numeric message
  counts against HEAD. Migration graph/dependency checks, plan-registry validation
  (55 entries), updated local links, handoff size limits and `git diff --check`
  passed. All active handoffs remain below 4,000 characters.

The minute poll does not guarantee a refresh completes within 60 seconds.
Successor ordering alone does not prove input consistency; matcher input-refresh
failures and best-effort after-commit delivery still require step 4's completion,
failure/retry and fencing work. Watermarks remain empty; certification is closed.
No live-generation publication, development-stack/production migration, fleet
run, timing benchmark, external validation, commit, push or deployment occurred.
Resume step 4 in a fresh session when directed, from `operations/BLUEPRINT.md`.

### Software implementation step 4 — guarded publication and durable admission

2026-11-11: user directed “next” after step 3. Implemented the bounded
publication boundary using existing Jobs state; the page still reads live
aggregates and `contract_ready` remains false.

- Unapplied migration 0409 adds a fenced `publish_software_overview` wrapper
  and removes ingest's access to the unfenced 0407 calculation function.
  Tenant, definition, scope, contract version, claim, cancellation, lease and
  wall-clock deadline are checked. Prerequisite revisions must be released
  and present in the recorded producer output. Calculation is serialized
  before it begins; the final claim check locks the Jobs row until commit.
- The same transaction computes all metrics, replaces one aggregate row,
  records input metadata and sets publication time. Before/after checkpoints
  cover latest input-owner completions, active handlers and request counts
  on executing/queued overview runs. Changed checkpoints abort publication.
  Metadata contains actual run IDs, completion events, declared output
  revisions and consumed dependencies; it contains no claim token or actor
  payload. Missing history is explicit (`observed=false`, NULL completion),
  not invented freshness or certification.
- A concurrent request remains assigned to its queued successor. Publication
  does not delete/consume that request or clear newer Jobs work. The existing
  minute expiry poll also retries a failed publication, including failed
  bootstrap; a migration with no prior request does not initiate a build.
- Operator lifecycle/finding/capability/identity and decision/policy changes
  now admit their overview/classifier work in the source transaction. Queue
  failure marks that transaction for rollback, even if a caller catches the
  exception. This deliberately replaces the prior best-effort after-commit
  admission. Internal helpers/callers were renamed accordingly. Risk matview
  convenience callbacks remain after commit; they do not certify a generation.
- Inventory safety publication now follows catalog and lifecycle projection,
  without adding another refresh. Lifecycle projection and matcher safety
  failures propagate to Jobs instead of reporting successful owner completion.
  The dispatcher forwards the claim to the Software producer. Existing Docker
  directory copies include all runtime changes; no dependency or service change.

Validation:

- Actual 0407, 0408 and 0409 SQL ran against a small network-isolated synthetic
  PostgreSQL 16 fixture. The aggregate retained eight installations/six titles,
  correctly stored owner/dependency/request metadata and stayed uncertified.
  Valid claim publication succeeded. Wrong/missing tenant, wrong role/token,
  expired lease/deadline, cancellation, unresolved/mismatched prerequisites,
  and failed/queued/running input owners rejected publication. Ingest could
  execute neither the private input reader nor the unfenced calculation.
- Concurrent checks paused only the fixture calculation using a test-only
  advisory gate. Readers retained the prior generation while a candidate was
  uncommitted. Changed upstream revisions, claim revocation, a deadline elapsed
  during calculation and a newly queued request each rolled the candidate
  back, preserving prior metrics, metadata and timestamps. The queued successor
  survived and then published; the older claim could not overwrite it.
  A failed attempt became retry-due; reverse/reapply succeeded. The temporary
  container and volume were removed. No service database was accessed.
- Local mocked checks passed for claim forwarding, transactional overview/full
  classifier admission, rollback marking on queue failure, rejection outside a
  source transaction, title/catalog/lifecycle/safety order, and propagated
  catalog/lifecycle/matcher failures. These did not invoke fleet work.
- Existing targeted checks: 37 Operations tests and 31 ingest tests passed;
  the same six registry/workflow expectation tests failed as at step 3. Five
  also failed against HEAD in the prior baseline comparison. Five unrelated
  PostgreSQL Home tests were deselected. No test files were changed in this
  step; previous excluded test edits remain preserved.
- Django system check, Python compilation, 0406–0409 migration graph, scoped
  lint, and new-migration/dispatcher formatting passed. Views retain 96 Ruff
  findings; remote-access/decision actions retain three combined. No additional
  normalized rule/function diagnostics were introduced. Matcher, registry and
  inventory whole-file formatting retain existing unrelated differences.
- Plan-registry validation (55 entries), updated local links, `git diff --check`
  and all three active handoff size limits passed. Checkpoints route to step 5.

Limits and next gate:

This fixture exercises the actual publisher SQL against minimal Jobs ledger
tables, not the deployed worker/admission stack. Latest owner checkpoints are
not exhaustive source-binding lineage or a substitute for assessment/source
freshness; absent history stays unknown. The guard conservatively withholds
publication after a latest failed/pending owner until it is reconciled. Full
dependency coverage, client-restricted reads, immediate decisions, reader failure
states and certification remain steps 5–6 and their acceptance review.

The existing minute poll cannot certify 60-second end-to-end completion, and no
cadence or throughput conclusion was inferred from fixture checks. Representative
validation remains separately authorized. Migration 0409's ordinary transactional
Jobs-history index build requires locking review before release; rollback must
use matching producer code. No development-stack/production migration, initial
live build, page cutover, fleet/timing run, external execution, commit, push or
deployment occurred. Resume step 5 in a fresh session when directed, using the
Operations checkpoint. All 15 navigation items remain open.

### Software implementation step 5 — protected reader prepared

2026-11-11: user directed “next” after step 4. Prepared unapplied migration
0410, `software_overview.py`, `_software_published_overview_data` and conditional
template states. The live `software_page` still calls its existing reader;
this preparation does not authorize certification or route cutover.

The selected immediate-decision mechanism is the contract's explicit pending
option. A committed decision/refresh request makes the next protected read
withhold metrics until a matching generation completes. No new live-decision
overlay, per-installation reconstruction or background request is added to reads.
The protected function requires separate certification, successful publication
with the matching generation, stable input-owner checkpoints, no newer overview
work/failure and unexpired exposure/window deadlines. Its payload uses an
explicit metric allowlist. Other states return explanation and original
timestamps without counts or labels; the retained generation stays in storage.

Migration 0410 revokes runtime access to the earlier certification-only view
and grants read-function execution only to application/readonly roles. The
application checks the existing Software permission, authentication/active user,
tenant and client context before any query. Client context is unsupported for
this tenant-grained publication and receives no summary, including labels.
There is no newly invented client-account authorization model. Only a current
result permits the existing bounded recent-detail and configuration reads.
Exceptions render unavailable, with no raw aggregate or Products fallback.

Validation:

- Actual 0407–0410 SQL ran on one small, network-isolated PostgreSQL 16 fixture.
  Missing/uncertified/pending/current/failed/expired/input-changed states behaved
  as specified. A synthetic eight-installation/six-title result was readable
  only after fixture-only certification and matching Jobs completion. A
  successful empty generation exposed real zeros. Service data was never certified.
- Wrong/missing tenant, wrong role, ingest execution, raw storage reads/writes
  and the view bypass were denied. Application and readonly reads agreed;
  a client-scoped call returned only unavailable/restricted-scope state.
- A decision plus queued request committed together made the next read pending.
  Failed publication/input states and both elapsed deadlines withheld payloads.
  Missing generation proof was unavailable. Original stored values/timestamps
  were retained, and repeated reads added no Jobs requests. Reverse/reapply
  succeeded. The fixture container and volume were removed.
- Mocked Python checks passed for JSON decoding, permission/tenant/client denial
  before queries, database-read failure, valid zero mapping, no raw/Products
  fallback and bounded detail/configuration wiring. Full-template renders hid
  accidental stale counts/private labels in pending/stale/unavailable states;
  they did not show false zeros or “nothing new.” Original result timestamps
  remained visible. Before step 6's authorized wording change, the guarded
  template rendered the existing live context identically after whitespace
  normalization.
- Django system checks and all 19 focused existing Software tests passed; five
  unrelated PostgreSQL Home tests were deselected. New module/migration lint
  and formatting, Python compilation and the 0410 migration graph passed.
  No test files were edited. Existing Docker source/template directory copies
  include every new runtime file. No service or dependency change was needed.

### Software implementation step 6 — wording corrected; acceptance open

User directed “next” during step-5 validation. The title review distribution
and summary now say “No open decision issue”/“without an open decision issue”
for the compatibility `approve` fallback. They no longer claim it measures
explicit approvals. Counts, internal keys, decision/coverage precedence and
explicit safety-band approval labels are unchanged. ADR-0037 and ADR-0039 remain
Proposed; no status was silently promoted.

Focused render checks verified the corrected four-title fallback and retained
two-title explicit safety approval wording. Products' function AST remains
identical to HEAD, the overview CSV branch retains its original dispatch, and
the live HTML route remains on its existing reader. Prepared-reader source
checks found no aggregate fallback or refresh/enqueue call.

Final local checks also passed for bounded-detail failure withholding, source
Ruff comparison (96 retained findings, no additional normalized rule/function
diagnostics), the plan registry (55 entries), updated local links, new-file
whitespace and all active handoff size limits. `git diff --check` passed.
The final protected-read fixture also rejected a newer completed Job without
the matching stored generation. Its container/volume were removed.

| Contract | Local evidence / remaining gate |
| --- | --- |
| P01 ownership | One Software producer, private storage and fenced publication. New schema remains unapplied. |
| P02 completed inputs | Owner/dependency watermarks and incomplete/failure guards checked. Full source-binding lineage, assessment freshness and complete writer coverage still require confirmation. |
| P03 atomic generation | Actual SQL/concurrent fixture checks preserve one complete prior generation on failure. Full worker-stack integration remains unverified. |
| P04 concurrent changes | Transactional admission, claim rechecks and queued-successor preservation checked. Existing Jobs integration still needs its focused end-to-end check. |
| P05 60-second freshness | OPEN. Minute admission alone is insufficient proof; representative queue/refresh/expiry throughput and contention are unmeasured. No new cadence is selected. |
| P06 immediate decisions | Protected next-read pending and immediate expiry guards passed synthetic checks. Authoritative input/writer coverage remains a cutover prerequisite. |
| P07 honest age/failure | Original timestamps, observed-history markers and missing/failed/expired/zero distinctions checked. Source/assessment-age coverage is not inferred from Jobs timestamps. |
| P08 compact request | Prepared reader uses one protected aggregate plus allowed bounded detail/config reads; no raw fallback. It is not active; full authenticated HTTP targets are unmeasured. |
| P09 recovery | Prior generation retention and existing Jobs retry path checked locally. Full bootstrap/retry behavior in the real worker stack remains unverified. |
| P10 security | Tenant, registered Software permission, runtime roles, client-context withholding and label suppression checked locally. Ordinary/client-restricted-account certification against the complete authority model is still open. |
| P11 compatibility | Products/CSV dispatch, metric definitions, decision precedence, runtime packaging and ADR statuses preserved. Final integrated parity remains part of acceptance. |

The previously recorded six registry/workflow expectation failures remain open;
no approval was given to edit tests. Migration/index locking, full Jobs/schema
integration, complete input/security coverage, representative <=60-second freshness
and full authenticated HTML <=1.5 seconds ordinarily/<2 seconds cold must be
resolved before enabling readiness or switching the route. Browser/network limits
must be reported separately. Test edits, service-database migration/initial build,
external validation, commit/push/deployment and cutover retain their explicit gates.

This is a local implementation/acceptance review, not full contract acceptance.
No service-database migration, initial live publication, certification, cutover,
fleet/timing run, external execution, commit or deployment occurred. All 15
navigation items remain open. Resume only these remaining gates in a fresh
session using `operations/BLUEPRINT.md`; do not restart design or add speculative
coordination infrastructure.

### Acceptance continuation — direct Software decision admin writer

User directed “next.” A bounded writer review found that Django's registered
`SoftwareDecisionAdmin` could save/delete decisions without the governed refresh
request used by the ordinary decision UI. This was a demonstrated gap in
P02/P04/P06 coverage, not a new feature requirement.

Only that admin writer changed: create/change, single delete and bulk delete
now call the existing full-classifier admission helper inside their source
transaction. Queue failure rolls back the source change. Unchanged existing
forms and empty bulk deletion do not request unnecessary fleet reconciliation.
The existing classifier successor supplies the overview request. Admin
permissions, decision precedence, models and schema remain unchanged.

Validation used actual Django ModelAdmin CRUD methods and real in-memory SQLite
transactions with two tiny synthetic models. Only the existing Jobs admission
call was stubbed to a synthetic request row. Create/update/delete/bulk delete
committed their request together, and each of four induced admission failures
rolled back both source and request writes. No-op saves/empty deletion added
no request. This proves transaction coupling for the hook, not PostgreSQL Jobs
admission/dispatch/claim integration. No fixture file or service database was used.

Django system checks, Python compilation and the 19 focused existing Software
tests passed (five unrelated Home PostgreSQL cases deselected). The admin file
retains its one import-order Ruff finding, also confirmed in HEAD; unrelated
imports were preserved. Existing Docker directory copies include the change.
No test files, dependencies, migrations, runtime configuration or live data changed.

Source coverage is still open. Registered finding-type, classifier/suggestion,
catalog/intelligence and authorization admin writers require their own bounded
review before claiming complete maintenance. Next: classifier/suggestion writer
coverage, then the remaining Jobs/security/freshness acceptance gates. Readiness
stays false and the live route stays unchanged. No commit, push or deployment.

### Acceptance continuation — classifier and suggestion admin writers

User directed “next.” `SoftwareClassifierRuleAdmin` and
`SoftwareSuggestionRuleAdmin` used default admin writes without the full rebuild
admission already used by the policy UI. Both now share the proven decision
admin transaction hooks through `SoftwareRebuildAdminMixin`. This consolidates
only the identical save/delete/bulk-delete behavior of those three admins;
no registry, scheduler, new Job or source authority was introduced.

Create/material change, single delete and nonempty bulk delete commit the
existing full-classifier request with the source change. Failed admission rolls
both back. Unchanged existing forms and empty bulk deletes request no work.
The prior decision-admin behavior, permissions and display configuration remain.

Actual Django ModelAdmin CRUD and real in-memory SQLite transactions passed
for all three admin classes: creation, update, deletion, bulk deletion, two
no-op cases and four induced failure/rollback cases per class. Only Jobs
admission was stubbed to a tiny synthetic request row. This is transaction-hook
validation, not full PostgreSQL Jobs integration. No fixture file or service
database was used, and no test files were edited.

Django system check, compilation, `git diff --check` and the 19 focused Software
tests passed; five unrelated Home PostgreSQL cases were deselected. Ruff retains
the same single import-order finding as HEAD; unrelated imports were preserved.
Existing Docker source-directory copies include the changed admin module.

Next bounded writer review: Software finding-type admin changes. Other declared
input writers, full Jobs integration and representative freshness/HTTP acceptance
remain open. No readiness, live-route, schema/dependency, migration, external
execution, commit, push or deployment change.

### Acceptance continuation — Software finding-type admin writer

User directed “next.” `FindingTypeAdmin` previously used default saves/deletes
without a Software refresh request. It now admits the existing full classifier
transactionally for relevant creation, policy changes and single/bulk deletion.
Relevance uses the existing Software category, classifier source modules,
Software subject scopes and the three compatibility title-bucket names.
Both saved and proposed values are checked, so moving a type out of Software
or renaming a bucket still invalidates its prior contribution. This does not
assign a new domain scope or change classifier/metric definitions.

Existing rows are locked before relevant saves/deletes. Bulk deletion requests
one rebuild when any selected type is relevant. Unrelated types, unchanged
forms, empty deletion and presentation/navigation/notification-only edits do
not request Software reconciliation. Source changes and admission roll back
together on failure; a protected deletion requests no work. Admin permissions,
models and schema remain unchanged.

Actual ModelAdmin CRUD with real in-memory Django/SQLite transactions passed:
nine relevance cases; category/module/scope/name transitions in both directions;
unrelated and presentation/no-op skips; single, mixed, unrelated and empty
deletion; a protected FK deletion; and four induced admission-failure rollbacks.
Only Jobs admission was stubbed. No service database or test file was used.
This validates the transaction hook, not PostgreSQL row-lock or Jobs integration.

Django system check, compilation, whitespace checks and 19 focused Software
tests passed (five unrelated Home PostgreSQL cases deselected). The changed
admin block matches Ruff formatting. Whole-file lint retains only the same
import-order finding as HEAD; unrelated formatting/imports were preserved.
Existing Docker directory copies include the changed runtime module.

Next bounded review: the writable product-authorization admin path. Remaining
declared writer coverage, full Jobs integration and representative freshness/HTTP
proof are still open. No readiness, live reader, dependency, migration, external
execution, commit, push or deployment change.

### Acceptance continuation — product-authorization admin writer

User directed “next.” `ProductAuthorizationAdmin` could save policy changes
without the rebuild request already used by the remote-access decision UI.
Its save hook now admits the existing full classifier in the source transaction
for creation or tenant/client/product/capability/polarity/withdrawal changes.
Unchanged and explanation/actor-metadata-only edits request no work. The existing
admin deletion denial and ingest migration 099's DELETE/TRUNCATE revokes were
reviewed and left intact. No new authorization precedence or inheritance was added.

Real in-memory Django/SQLite transaction checks passed for create, permit/deny,
client/global scope, product/capability changes, withdrawal/restoration,
explanatory/no-op skips and retained admin deletion denial. A small synthetic
withdrawal-reason constraint rejected an invalid write before admission. Four
induced admission failures (create, deny, scope change, withdrawal) rolled back
both policy and synthetic request rows. Only Jobs admission was stubbed; this
does not establish PostgreSQL authorization or full Jobs integration. No service
database, fixture file or test-file edit was involved.

Django checks, compilation, whitespace checks and 19 focused Software tests
passed (five unrelated Home PostgreSQL cases deselected). The changed hook
matches Ruff formatting; whole-file lint retains only the same import-order
finding as HEAD. Existing Docker directory copies include the admin change.

Next: finish the remaining declared-writer coverage map in one bounded review,
then full Jobs integration. This remains within the original contract's input
maintenance requirement; it does not authorize new features or infrastructure.
Representative freshness/HTTP proof, readiness and cutover remain open. No
schema/dependency, live-reader, migration, external execution, commit or deployment
change occurred.

### Acceptance continuation — declared-writer map completed

User directed “next.” Completed one bounded source review of the seven declared
input families. The [writer coverage map](PLAN-056-software-writer-coverage.md)
is now the authority for this maintenance review. It records existing owner
paths, explicit exclusions and four finite repair groups:

- **W1:** remaining direct capability/authorization/finding writes and their
  metric-relevance boundary;
- **W2:** catalog, publisher-alias, matcher-hint and capability-mapping policy
  completion through existing owners;
- **W3:** Computer/association/source-support changes, reusing existing ownership
  dirtiness instead of creating competing writers or another dirty store;
- **W4:** readiness/exposure completion after eligibility/status/policy changes,
  including newly activated condition policy.

The review confirmed gaps outside Django admin: ordinary
`software_capability_decide` and `software_product_authorize` save/audit without
Software admission. It also confirmed that migration 114's effective exposure
view reads materialized status with live decisions/deadlines; rebuilding only
the aggregate after a finding resolution does not refresh that input. The
prepared Jobs-only checkpoint does not observe ownership dirty rows. These are
maintenance obligations still needing implementation/proof, not merely missing
performance measurements.

Read-only evidence/EOL-map surfaces, descriptive category truth and the legacy
SoftwareCatalog detail relation are explicitly excluded where the reviewed
summary does not consume their edits. No new hooks were added speculatively.
The map also specifies one real Jobs admission/dependency/claim/finish integration
sequence with small synthetic inputs and no live source acquisition.

AST/source assertions corroborated missing UI/admin hooks, read-only bases,
legacy-catalog non-use, policy activation and exposure view boundaries. Local
links/whitespace were checked. No runtime/test files, database, migration,
dependency or release changed in this review. Existing unit/in-memory checks
are not relabeled as full Jobs integration. Readiness and the live route remain
unchanged; all 15 navigation items stay open. Next: the map's shared Jobs API
check, then W1–W4 cases as repaired, followed by the separate representative
freshness/HTTP/security and cutover gates.

### Software remaining implementation pass — 2026-11-12

User requested completion in one continuous pass with proportional validation,
without new test-file work. The finite W1–W4 implementation is locally wired;
the updated [writer map](PLAN-056-software-writer-coverage.md) owns its current
coverage and exclusions. Existing unrelated changes, migration 0406 and prior
test-file changes were preserved.

- W1: ordinary capability/authorization admission; shared finding relevance and
  guarded FindingAdmin CRUD; manual operator resolution preserved.
- W2: relevant catalog/matcher policy admins invoke existing local owner
  functions through one internal Jobs definition, then classifier and overview.
  Platform mappings use the classifier. No source acquisition was added.
- W3: relevant Computer/client/source-support admin and candidate-association
  writes admit the existing ownership owner. Existing dirty ownership blocks
  prepared reads/publication and is admitted by the existing scheduler.
- W4: readiness, existing evaluator-owned assessments, exposure and aggregate
  publication share one cursor/transaction. Active condition policy and
  client/global readiness-setting changes admit dependent overview work.
  Assessment preparation is restricted to findings with an existing Software
  condition assessment, including when another owner shares the finding type.
  It does not emit/reopen/resolve findings.

A schema-only isolated PostgreSQL fixture with synthetic metadata/data exercised
actual Jobs admission, dependency release, dispatch, claim/progress and finish:
full classifier → overview; local catalog-policy → classifier → overview;
empty ownership → overview; guarded finding creation and ordinary resolution
with pending/current behavior; coalescing and a preserved queued successor;
wrong/stale claims; induced failure retention and retry. A failure after actual
readiness/assessment/exposure preparation preserved the prior aggregate and
assessment rows/timestamps, and existing expiry/retry admission recovered.
Fixture certification toggles did not affect service databases.

Important limits: fixture intelligence flags were disabled, so catalog policy
traversed the registered local owner calls and empty catalog projection, while
matcher/EOL bodies skipped by configuration. This does not prove populated
publisher-alias remapping, matcher-hint effects or every admin/association
transition. Functional worker execution used the fixture migration-owner login:
the development ingest role lacks a preexisting finding_types SELECT grant.
No service grants were changed to bypass that limitation. Actual operations_app
protected reads denied private table/old-view access and client-scoped metrics;
page reads did not create requests. Runtime worker-role authorization and full
security certification remain open.

Migrations 0407–0410 applied in the throwaway fixture; no service database was
migrated. Its stale structural Jobs metadata required current repository
resource/claim definitions in the fixture, not a production patch. The fixture
container and its volume were removed and absence verified. No customer/source
rows or private settings were copied.

Django system check and 19 focused existing Software checks passed (five Home
PostgreSQL cases deselected), plus two existing assessment/readiness checks.
Registry definitions and the 55-entry plan-registry validator pass. Changed
modules compile; ingest/helper lint passes.
Changed producer/admin blocks were formatted without reformatting unrelated
files. Whole-file admin/finding-registry/view lint retains preexisting findings;
six previously recorded Jobs expectation failures remain unresolved and were
not rerun or edited. No new or modified test files were made in this pass.
Existing Docker directory copies package the changed runtime files.

Implementation completion is not contract acceptance. All outputs remain
contract_ready=false, and the default Software route still uses its live reader.
All 15 navigation items remain OPEN. Remaining activation gates are actual
runtime-role/security verification, representative <=60-second freshness and
complete HTTP <=1.5-second ordinary/<2-second cold-path proof, reviewed service
migrations, certification and approved cutover/release. No new dependency,
service, store or cadence; no live build, external execution, version change,
commit, push or deployment.

### Software activation review — 2026-11-12

Reviewed current working migrations, protected reader, existing runtime role
boundary, Docker packaging and Operations migration entrypoint. The next action
is a metadata-only deployed preflight, prepared as
[scripts/diagnostics/plan056_software_activation_preflight.sql](../../scripts/diagnostics/plan056_software_activation_preflight.sql).
It uses a read-only transaction, five-second statement/one-second lock limits,
and returns only the six relevant migration names and fixed role/object
privilege booleans. It neither calls producers nor reads source/customer rows.
The SQL was source-reviewed, not executed against an external database.

Release dependency: 0407 depends on existing Home migration 0406, which depends
on 0405. Operations startup applies all pending Django migrations. Therefore a
Software deployment cannot silently exclude pending 0406; review and explicitly
include it in migration approval, or separately approve changing the dependency.
No migration/dependency was changed during this review.

Verify deployed metadata before proposing a grant: the local fixture's missing
finding_types SELECT permission does not establish production permissions.
Do not substitute migration-owner execution for runtime worker verification.
After this preflight, representative acceptance still needs an authorized
environment with the candidate runtime files/migrations, a governed publication,
and a separately controlled prepared-reader/certification path. The deployed
live-reader route alone cannot measure the candidate's HTTP performance.
No grant, migration, source rebuild, certification or cutover is authorized by
this review. Existing test expectation failures remain explicitly unresolved.

### Deployed metadata-only preflight — 2026-11-12

User answered “next” to the request to run the prepared read-only preflight
on am-ch-01. Used the documented Invoke-DevTool.ps1 SSH helper, direct psql,
read-only transactions and five-second statement/one-second lock limits.
Only migration names, fixed object/role metadata and privilege booleans were
returned. No source/customer records, connection strings or query text were read.
The follow-up metadata queries are retained in the same preflight SQL file.

Actual results:
- 0405 and Home migration 0406 are applied. Software 0407–0410 are not.
  The earlier warning that 0406 might be pending is resolved for this target;
  its local working-file diff is still separately reviewable.
- ninja_ingest has SELECT on findings, condition_assessments,
  condition_participants and software_device_readiness. It lacks SELECT on
  finding_types and device_software_exposure_current, and lacks owner-role
  privileges on the latter. Both queried relations are owned by operations_migrate.
- The new overview table/view do not exist, consistent with unapplied 0407.
- Observed connections named ingest used one distinct database role, different
  from ninja_ingest, with superuser privileges and the required finding-type
  read/exposure-owner access. This is pool metadata, not per-process proof of
  which connection belongs to the Jobs worker.

Conclusion: the restricted-role gap is real, but it does not establish failure
of the currently observed runtime pools. Do not patch grants on that assumption.
Conversely superuser execution cannot prove the contract's restricted runtime
security boundary. Before acceptance, explicitly resolve the intended candidate
execution-role boundary and verify the governed producer under it. No role
switch or permission change is approved by this metadata check.

This check closes only deployed metadata verification. Service migration,
candidate runtime/security acceptance, representative freshness/full HTTP proof,
certification, cutover, commit/push and deployment remain separately gated.
No migrations, Jobs requests, producers, grants or service changes were executed.

### Existing worker-role design reviewed — 2026-11-12

User directed “next.” Repository source corroborates the deployed pool result:
Compose ingest and jobs-worker share the same private configuration directory;
jobs_worker and jobs_child initialize db with settings.postgres_dsn, whose login
comes from POSTGRES_USER. Neither child startup nor dispatcher switches to
ninja_ingest. No private configuration values were read.

The ownership note in sql/migrations/093_capability_assertions.sql explicitly
documents superuser ingest and the resulting unenforceable ingest-to-operator
privilege boundary. Root TODO already retains dedicated non-superuser ingest
as a separate concern requiring credential/role design and approval.
operations/DESIGN.md's current-role naming table instead says ninja_ingest.
That naming description conflicts with startup behavior and the observed
deployment; it is not authority to change runtime credentials.

Recommendation: retain existing runtime configuration for a separately approved
candidate functional run. Do not broaden ninja_ingest grants, grant membership
in operations_migrate or introduce a platform role migration as incidental
Software work. This is a scope recommendation, not permission to run the
candidate and not a waiver of ADR-0058.

ADR-0058 requires protected consumer reads and controlled writer privileges.
The application reader remains restricted; the shared superuser writer bypasses
ACL/RLS enforcement. Functional success under that writer cannot demonstrate
the full security contract. Security acceptance remains open until an explicitly
approved disposition; do not silently reinterpret “runtime roles” to exclude
the writer or mark sole-writer enforcement proved.

Concrete candidate execution still needs approval for an identified
representative environment, the reviewed pending Software migrations 0407–0410,
a governed initial publication and candidate reader checks. Live certification,
route cutover and production deployment are separate from that check.
No new implementation, role/grant/configuration change, external operation,
test-file edit, commit or deployment occurred in this source-review step.

### Minimum activation boundary — 2026-11-12

User ruled out further complication. No role redesign is added; retain the
existing superuser security limitation without declaring it fixed or waived.

Source confirms the page still uses the live reader; the prepared reader is
separate, and publication inserts/resets contract_ready=false. Deployment or a
one-off certification flag alone does not constitute sustained activation.

Minimum representative acceptance needs reviewed candidate code and 0407–0410
installed in an identified environment, governed publication, compatibility/
protected-state checks, <=60-second freshness and full HTML <=1.5-second
ordinary/<2-second cold proof. Only production am-ch-01 is configured; no
rehearsal target is identified. Do not time the old live page or benchmark the
workstation as a substitute. No further external operation occurred.
Installation, migration, initial build, certification and cutover require
authorization; commit and push approvals remain separate. Documentation
whitespace and plan-registry checks pass.
