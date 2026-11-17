# PLAN-056 — Task 5 read attribution

2026-11-10: local tracing started; task 5 remains incomplete. No new production
access or application/test edits. Goal: connect measured slow reads to shared
and page-specific work, before choosing remedies. Prior observations and
limitations remain in the [evidence record](PLAN-056-platform-performance-assessment.md).

## Source identity and evidence strength

Compared HEAD `ca00938a` and working-tree ASTs. Default route functions other
than Home match HEAD: org_index, devices_page, findings_queue,
_software_page_data, patching_queue, sources_status, source_records, admin_jobs
and admin_settings. Context processor is unchanged. Local Home, middleware,
issue_selection._items_sql/home_data and software_review.home_summary contain
uncommitted changes. Do not assign the measured deployed timings to those
uncommitted versions. Selected deployed hashes matched HEAD in task 3; later
Coverage diagnostics checked the deployed Coverage/selector ASTs. None of this
certifies every deployed file today. The next collector gates its actual two
reader functions against reviewed ASTs before connecting.

Evidence classes: task 4 HTTP timings are whole requests; global resource/SQL
counters include concurrent work. Coverage has separately attributed execution
and plans. Other components below are static code findings, not measured shares.
Do not add component timings from separate runs into an HTTP breakdown.

## Shared request work

- TenantMiddleware scopes requests in a transaction; production settings also
  use ATOMIC_REQUESTS. Keep tenant/session hooks and RLS intact. No measured
  evidence makes this safety boundary a performance culprit.
- `context_processors.brand` loads all nondeleted Client model rows, ordered by
  display name, on every authenticated non-Home render. It is a separate read
  from page-specific client-choice SQL and uses a wider model projection.
- Issues and Patching badges use tenant-keyed cache entries with 60-second TTL.
  Settings has no view-body query, yet still incurs this shared work plus three
  admin candidate counts. First/repeat differences could reflect badge/database
  warming or workers; neither cache-hit nor individual-cost attribution exists.
- `_nav_issues_count` uses governed `issue_selection.count`, not a raw Finding
  count. Selection includes independent-action ranking, covered state, candidate
  unions and ownership/attribution logic. The common count can be costly even
  without a detail page. Actual pruning/function calls need measurement.
- On Home, `home()` sets `request.home_issues_open_count`, so the shared Issues
  badge reuses that value. The Patching badge still checks its own tenant-keyed
  60-second cache and runs a separate active-Finding count on a miss; its
  population is not established as equivalent to the Home Patching actions.
  The three admin candidate counts are skipped on Home. These paths are static
  local findings; cache state and runtime cost were not measured.
- `/admin/` renders additionally count open merge/client candidates and pending
  entity candidates. This applies to measured Settings and Jobs.

## Route/consumer map

| Measured route | Confirmed default read work | Limit placement and evidence gap |
| --- | --- | --- |
| Home `/` | Client, Computer, source-record, Issues, Patching, Coverage and Software summaries, then source-binding/job summaries. Home reuses its Issues open count for navigation. | One direct reader pass: device policy 0.027 s, Clients 0.016 s, Computers 0.271 s, source inventory 1.716 s; Issues hit its 3 s statement deadline at 3.019 s. Later readers were not attempted. These are component timings, not HTTP shares. Shared context, badges, rendering and remaining readers are still unmeasured. |
| Clients `/orgs/all/` | Annotated client/device counts, source references, device-type/platform totals, build_client_directory; directory adds location/user/health context and finding/software-exposure rollups. | Entire client directory assembled. No evidence that it calls build_client_workspace once per client; it uses its own aggregate path. No component cost yet. |
| Computers `/devices/` | Count/filter/facet reads over v_device; findings/source-health enrichment and bounded row SELECT. | SQL pagination exists; aggregate and view cost can precede it. Filtered/software/CSV variants not measured. |
| Coverage `/inventory/computers/` | Eight initial raw SELECTs, fleet inventory/filter assembly, then Hudu/source-detail reads and render context. | Python pagination happens after fleet reads/assembly. Hudu lifecycle branch is measured: original deadline, improved candidate plan, sampled parity and full candidate 0.374 s. Remaining phases and full-page candidate unverified. |
| Issues `/findings/` | Policy/taxonomy, fleet open/paused independent-action counts; filtered counts where needed; selected leaf count/page and item hydration. | Default fleet header counts are reused when the base scope matches; no claim they are always duplicated. Leaf page is SQL-bounded, aggregate/ranking work precedes it. |
| Sources `/sources/` | Health/observation aggregate, per-instance/type record aggregate, active source-refresh runs, latest per-binding runs, recent 30 runs. | Both observation views aggregate before output. Health counts all observations; record counts exclude companion streams, so these are not interchangeable totals. |
| Source Records `/inventory/source-records/` | Source choices, matching count, global distinct types/layouts, client choices, materialized 100-row page, then relationship/mapping and issue enrichment. | Main extras are joined after page selection. Count/facets precede pagination; ordered page selection can still scan/sort broadly. Default count does not apply client/search/reason filters. |
| Software `/software/` | Availability probes, fleet risk distribution, capability/category totals, current-title aggregation, workflow/publisher/exposure/finding summaries. | Default overview sets title_page_size=0; it does not transfer 500 title rows. current_titles still supplies totals. Other title/filter/CSV variants differ. Actual CTE pruning/cost unmeasured. |
| Patching `/patching/` | Governed finding tiles, posture CTE totals/client groups, posture count/page; finding hydration and row formatting. | Device page uses SQL limit 100, but finding rows are formatted before Python Paginator(50). Posture CTE appears in multiple statements; per-client compliance breakdown is conditional, not a default fleet cost. |
| Settings `/admin/settings/` | Render-only view plus shared context/admin counts. | Useful shared-work lead; first/repeat HTTP times do not isolate navigation. |
| Jobs `/admin/jobs/?refresh=off` | Jobs health/runtime/catalog diagnostics and status/scope summaries, then shared context/admin counts. | Some small catalog sections are drained in 100-row pages, not necessarily one bounded database query. HTTP collector executed no polling JavaScript. |

## Shared relation and function leads

- Sources health (`0116_generic_admin_read_models`) aggregates observation
  counts/latest timestamps. Source record counts (`0397_source_record_companions`)
  groups the same store with a different population and an is_companion_stream
  predicate. That SQL STABLE SECURITY DEFINER function reads the companion
  registry/source-instance match. Its call count/cost is unmeasured.
- `v_entity_observation_admin_metadata` serves Source Records, Home's source
  summary, source-record detail/list, client-domain, naming and finding-review
  readers. Preserve masking and restricted-layout behavior. A shared-view change
  could affect all those consumers; counts do not prove every JSON projection
  executes, because planning may prune unused columns.
- Coverage's lifecycle view also serves Coverage's source-record totals and Computer source
  details. Its editable policy (ADR-0011) cannot be replaced with raw archive
  flags. The correlated query is a diagnostic candidate, not a deployed fix.
- Software uses current installations, catalog capability/category and safety/
  exposure readers across Home, Overview/Products, client software and workflow
  counts. Multiple aggregates and sorts are leads; global temp-file deltas do
  not identify which statement spilled or prove all selected CTEs execute.

## Attribution gaps and next action

Missing: shared navigation/badge/query timings and actual cache state; Home
summary shares; Sources/Source Records components; Software aggregates;
Patching repeated reads; remaining Coverage SQL/Python/template work; ordinary
roles and unmeasured variants. No cache/index/summary/schema proposal is adopted.

First frontier: the exact Sources five SELECTs plus Source Records default
count/types/layout/client choices. These routes remained slow on both measured
requests and have concrete aggregate/view leads. The prepared
[nine-component execution review](PLAN-056-source-reads-execution.md) supplies
runtime-role source gates, per-statement server deadlines, redacted results and
stop-on-failure. It does not measure the wider navigation Client ORM query,
fetch the Source Records page rows, execute a page or rerun jobs. After results,
follow the identified component or select the next named frontier. Keep task 5
open until measured costs/consumers and remaining hypotheses are accounted for.

## First frontier result — 2026-11-10

The user instructed proceeding with the exact nine-component protocol. One
runtime-role pass completed sources_health in 0.643 s (17 rows), then
sources_record_counts hit its 3-second server deadline (57014, 3.008 s observed).
Remaining seven components were not attempted. Connection closure and
hash-verified cleanup confirmed. See the
[execution outcome](PLAN-056-source-reads-execution.md#execution-outcome--2026-11-10).
No app/test changes, retries or other-work cancellation.

The approved non-ANALYZE plan completed in 0.084 s with nine nodes and no
truncation; it shows the broad tenant scan/aggregate path but cannot expose the
companion-function runtime share. Source Records page plan and bounded read
also completed: the plan shows broad candidate sorting/mapping estimates and
the read hit its 3 s deadline. Full details are in
[Sources count plan](PLAN-056-sources-counts-plan-execution.md),
[Source Records page plan](PLAN-056-source-records-page-plan-execution.md),
and [page read](PLAN-056-source-records-page-read-execution.md). Remaining
Sources history, other Home readers/context, Software, Patching and later
Coverage phases remain gaps.

## Home reader pass — 2026-11-10

The approved one-shot direct-reader pass is documented in the
[execution record](PLAN-056-home-components-execution.md). It attributed a
statement deadline to `issue_selection.home_data()` and measured source
inventory at 1.716 s in that pass. It stopped on the first failure, so Patching,
Coverage, Software, Sources and Jobs reader costs remain unknown. Context,
navigation, badges and HTTP rendering were outside scope. Do not add these
component measurements to the task 4 request times as an exact breakdown.

One later non-ANALYZE EXPLAIN of the exact Home Issues aggregation completed
in 0.185 s and returned 59 planner nodes. A visible branch estimates 54,825
finding rows through the status/severity bitmap path; multiple aggregation and
unique branches remain. The tool display clipped the node list; visible
summary findings are in the [plan record](PLAN-056-home-issues-plan-execution.md).
No actual execution cost share or timeout cause is established.

A separately approved pass for the Home readers after Issues measured the
device-policy dependency at 0.025 s, then the Patching component hit its 3 s
statement deadline at 3.009 s. Coverage, Software, Sources and Jobs were not
attempted. A separately approved non-ANALYZE plan of the Patching query took
0.079 s and returned 52 nodes. Estimates include sequential scans of current
devices, patching scope, sessions and ownership, plus an activity scan; patch
outcomes use the primary-key index. Planning estimates do not establish the
3-second execution cause. See the [remaining-reader execution record](PLAN-056-home-remaining-execution.md)
and [Patching plan record](PLAN-056-home-patching-plan-execution.md).

## Home shared-context and remaining-reader review — local static, 2026-11-10

Reviewed the current working-tree Home view, `context_processors.brand`,
tenant/client middleware, Coverage reader, source binding summary and Jobs
summary. This is not a claim about the deployed Home version: the view and
middleware contain uncommitted changes, while the context processor is
unchanged from HEAD.

The current Home path calls device policy, Clients, Computers, Inventory,
Issues, Patching, Coverage, Software, Sources and Jobs in that order. Its
60-second process-local cache is used for Inventory, Issues, Patching and
Software. Clients, Computers, Coverage, Sources and Jobs are uncached in this
working-tree version. Summary age allowance does not waive the cold-navigation
target. Coverage is one domain-reader query with a small policy SET; Sources is
one binding/latest-run query with two `DISTINCT ON` CTEs over source-refresh
runs; Jobs calls the restricted health and runtime diagnostic functions. The
source and Jobs readers are called unconditionally; only their cards are
assembled for staff.

The Home context processor omits the global Client ORM roster, reuses the Home
Issues count for its Issues badge, and still resolves the independent Patching
badge. It skips admin candidate counts outside `/admin/`. TenantMiddleware
opens the tenant-scoped request transaction; Home-specific timing/cache setup
in middleware is uncommitted. No timing was collected for the Patching badge,
context rendering, middleware or HTTP work, and no cache hit/miss was observed.

The approved three-reader pass completed Coverage in 0.254 s, then Software
hit its 3-second statement timeout at 3.010 s. Stop-on-error left Sources
unattempted; Jobs was outside the approved scope. No Patching retry. See the
[execution record](PLAN-056-home-next-three-execution.md). A plan-only
diagnostic of Software would be a separate approval gate.

The user then approved a five-check sequence: Software EXPLAIN, Sources reader,
Jobs reader, and two Home `brand` context calls to compare a cold and warm
Patching-badge cache lookup. Both Software-plan invocations so far passed source
hashes but stopped at an overly narrow AST shape check before DB access; exact
cleanup was confirmed. The four later checks were not attempted. A corrected
gate now matches the deployed full Software query to its historical local
commit. The corrected Software EXPLAIN subsequently completed in 0.178 s with 56 nodes and confirmed closure/cleanup. The other four checks remain authorized; repeated approval requests were unnecessary. See
[Software plan protocol](PLAN-056-home-software-plan-execution.md).

## Remaining Home checks — bulk outcome, 2026-11-10

The user's resource-saving/bulk instruction was applied to the four remaining
checks in one invocation of `scripts/diagnostics/plan056_home_bulk.py`, SHA-256
`3e6d514f4e0ef43c0cf273139452d7bbc64e314014b66174e3aec25b82123723`.
Views and context-processor byte hashes matched committed HEAD before execution
and their deployed gates passed. One existing-role connection, tenant 1,
repeatable-read/read-only; 3 s statement, 1 s lock, 5 s idle and 60 s process
limits; stop on error. Fresh LocMem cache was confirmed without flushing.
The synthetic Home request supplied its Issues count and bypassed HTTP/auth/
session/template work. Reader availability was checked in memory; return values
were discarded. Output contained timings/error/closure only.

Backend 361991: Sources 0.332 s; Jobs 0.195 s; Home brand context cold 0.325 s;
warm 0.000 s at millisecond rounding. Status 0, connection closed. Exact
host/container hashes matched before cleanup; files and empty directory removed
and absence confirmed. No business writes, Jobs execution or HTTP calls.

All five authorized checks are complete, including the earlier Software plan.
Cold/warm here describes this fresh diagnostic process's navigation cache,
not an HTTP request or database cache. The synthetic context excludes real
session/user loading. Separate component runs cannot be summed into an exact
Home response breakdown. The major measured Home frontier remains Inventory,
Issues, Patching and Software; no remedy is selected. Full-page acceptance,
write/job contention attribution and remaining route review are still open.
