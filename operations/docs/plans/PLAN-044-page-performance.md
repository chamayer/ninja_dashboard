# PLAN-044 — Navigation and Computers performance

Status: active. On 2026-11-09 the user authorized autonomous performance work, validation, commit, and push as needed. Home target: 1.5 seconds or less; hard maximum: 2.0 seconds. Preserve the agreed Home design and existing domain-owned summaries. No schema changes or local performance measurements.

## Home requirements and domain-data inventory (2026-11-05)

### Requirements

- Put the domain overview before “What needs attention.” Keep Needs attention
  as a distinct prioritized work list.
- Represent every major Operations area with a meaningful owner-provided
  total/KPI and, where existing history supports it, a total trend no longer
  than 30 days. Coverage is the agreed exception: show current Computer status
  totals without a separate Home issue trend or snapshot storage.
  Show freshness and denominators where they affect interpretation, and link
  each summary to its owning workflow.
- Home composes domain-owned summaries; it does not recalculate domain state,
  status precedence, ownership, coverage, or trend meaning.
- Keep the detailed per-client portfolio, ranking, filters, and comparisons on
  Clients. Home may retain the fleet client total and a link to that portfolio.
- Prefer existing domain-owned history/current projections for trends. Missing
  trend ownership is a design gap, not a reason to query raw event history ad
  hoc. Do not choose storage or schema changes before review.

### Current surface and ownership inventory

The current local `home()` composes summary readers and a governed attention
list. The template puts the domain cards above “What needs attention” and links
to the Clients portfolio; it no longer renders the portfolio table. Inventory
source-record counts exclude companion observations that have no admitted
record subject.

| Operations area | Current owner-side data/readers | Current Home use and mismatch | Historical total available in the current implementation |
| --- | --- | --- | --- |
| Clients | `client_workspace.home_summary()`; `Client.created_at` / `deleted_at` | Owner supplies the current active-client total and same total 30 days earlier. Home displays the net comparison; detailed portfolio remains on Clients. | Current temporal fields support the cutoff count; client retirement is one-way in the application workflow. |
| Computers | `computer_reads.home_summary()`; device lifecycle and change history | Current, active, retired, and review counts are supplied by the owner. Home shows no trend because historical ownership/lifecycle reconstruction would read generic change history without a time-leading index. | No suitable bounded owner total at the cutoff. |
| Inventory | `source_record_views.home_summary()`; `source_record_subjects` and `entity_observation_history` | Owner supplies current present record subjects, the same record population at 30 days earlier, and latest report time. Companion streams are excluded because they are details attached to records, not source records. Additions/withdrawals stay on Inventory. | Observation intervals retain 90 days and have tenant/effective-time indexes. Migration 0096 requires one open interval per active current observation; cutoff intervals are joined to admitted record subjects. |
| Patching | `patching_reads.home_summary()`; current Patching scope and `patch_facts` | The local reader supplies current/in-scope/excluded/unmanaged totals, active recent in-scope Computers and their share of all current Computers, and 30-day outcomes filtered to in-scope devices. Home shows the scope split, active share with numerator/denominator, and outcomes as a KPI; it does not label events as a trend. | No as-of scope total is exposed by this reader. Static contract review only; the local query has not been runtime-validated. |
| Security & Coverage | `coverage_reads.home_summary()`; current evaluator `device_requirement_state` | The local reader supplies Computer-level meeting/not-meeting, stale, neutral, and exempt counts. Home shows meeting in green, not meeting in red, and the separate populations. No trend is shown. | Current verdict state only. User declined added Coverage snapshot/history and decided no separate Coverage trend on Home. The local query has not been runtime-validated. |
| Software | `software_review.home_summary()`; current installations, decisions, and title-linked findings | The local reader supplies installed-title count and approval split using the Software page's title-status CTE/population. Its risk count includes active product/version concerns and facts keyed to installed titles, plus installation-scope concerns joined to current installation UUIDs. Home shows no trend. | SCD2 installation history exists, but an as-of total with the same stale-evidence and current-Computer filters is not exposed by the owner. |
| Issues | Governed `issue_selection.home_summary()` and `home_attention_items()` | Current actions and prioritized attention use the Issues owner. Home shows no trend because the historical independent-action total is not reconstructable from current finding state alone. | No suitable historical open-action total is exposed. |
| Sources and Jobs (Admin) | `_sources_home_summary()` and `_jobs_home_summary()` remain in `views.py` | Staff cards show current status. Home no longer substitutes run-event counts for total trends. | No owner-side as-of total is exposed to Home. |

This is a static code/schema inventory, not a production-data inspection. The
PLAN-019 history is now in the main checkout. The owner readers support a
same-definition 30-day total for Clients and Inventory. Existing event counts
are not total trends; Home omits a trend where the owner cannot provide an
appropriate cutoff total from existing history without an unbounded history
scan or new storage.

### Confirmed KPIs and total-trend requirement

Use the current total and its historical value at a cutoff no more than 30 days
earlier when the owner already retains suitable history. Do not substitute
created, observed, installed, failed, first-seen, or closed event counts for a
total trend. Coverage is the exception: show current status totals and no
separate Home trend. Home arranges owner-provided values; movement explanations
stay on domain pages. Confirmed KPIs are:

| Area | Confirmed Home KPI | Owner-page explanation |
| --- | --- | --- |
| Clients | Active-client total | Client additions and withdrawals/details remain on Clients. |
| Computers | Current Computer total and useful current lifecycle counts | Explain lifecycle movement on Computers. |
| Inventory | Current source-record total and reporting freshness | Show additions and withdrawals on Inventory. |
| Patching | All Computers in scope; in-scope/excluded/unmanaged split; share of all tracked Computers actively patching; outcomes only for in-scope machines | Explain patch outcomes and recent activity on Patching. |
| Security & Coverage | Current Computers meeting requirements (green) and not meeting (red); stale separately; exempt excluded; no applicable requirements neutral; no separate Home trend | Explain missing/stale movement on Coverage. |
| Software | Installed-title total, approval split, distinct installed titles with at least one active title-linked risk finding | Explain approval and title-risk movement on Software. |
| Issues | Governed open independent actions and critical actions | Explain finding changes on Issues. |
| Sources and Jobs | Useful current source and job status totals | Explain refresh and run outcomes on their owning pages. |

Keep each calculation in its existing owner. Home formats returned values.
Do not add a shared metric engine, duplicate summary layer, or schema. Preserve
the owner page's current Computer, finding, and source populations. The current
owner-summary additions must be reviewed against these contracts before further
Home code is added.

### Design direction (2026-11-05)

The user asked us to pursue this as a goal and cautioned against overengineering
or layering quick fixes onto a flawed design. Keep the implementation direct:

- Reuse an existing domain-owned summary/read model when it already has the
  required meaning. If Home currently owns a needed calculation, move that exact
  definition into the existing domain owner; do not add a dashboard framework,
  generic metric engine, common semantic calculator, or redundant summary layer.
- Home may format and arrange returned values, but it must not infer ownership,
  domain status, coverage, or trend meaning. A consistent template context is
  fine; domain semantics stay with the owner.
- Keep client-specific detail and ranking on Clients. Home links to that page
  and uses only a client total/KPI supplied by Clients.
- Each shown trend compares the same owner-defined total at two points no more
  than 30 days apart. If existing domain history cannot support that, do not
  substitute event counts or add schema. Coverage has no separate Home trend.
- Preserve existing populations, ownership, queue, and drilldown contracts.
  Do not run performance experiments or make schema changes.

The previous proposal for a new summary function in every domain was too broad
before confirming which owner APIs already exist. The inventory must first
identify the smallest owner-side change needed for each card. No implementation
should build on the earlier proposal as a framework design.

### User-confirmed KPI direction (2026-11-05)

The Software card should show installed-title count with an approval-status
breakdown. The user also selected a count of distinct installed titles with at
least one active, title-linked risk finding. Count each title once; include
unauthorized software only when represented by a title-linked finding, and do
not invent a combined risk score or include unrelated device-level findings.
The specific risk finding population must use existing Software/Issues
semantics. The user resumed implementation on 2026-11-05; tests and performance
measurement remain separately gated.

For Inventory, Home shows the current source-record total against the total
30 days earlier and the latest-report freshness signal. Inventory explains
additions and withdrawals on its own page; Home does not add separate movement
counts. Use existing presence history; do not infer movement from repeated
reports.

For Patching, installed/failed outcome counts cover all machines in the
in-scope Patching population. Retain the full population's in-scope, excluded,
and unmanaged dimension. Home should also show the share of all tracked
machines with recent patch activity, reusing the Patching page's active +
in-scope + recent-activity definition; label the numerator and total
denominator clearly.

For Security & Coverage, the user selected paired Computer-level totals:
Computers meeting requirements (green) and not meeting requirements (red),
using the Coverage owner's rule. Missing requirements count as red; stale
requirements are separate; exempt checks are excluded; Computers with no
applicable requirements get a separate neutral count.

The user selected the existing under-two-second ordinary-page response target
for Home. This is a goal for later validation, not evidence about current
performance or authorization to measure while work is paused.

### Required domain-page movement details

Home shows the total trend. Each owning domain page must explain the relevant
movement and provide its drilldown before PLAN-044 is complete: Inventory
additions/withdrawals; Patching outcomes and recent activity; Coverage
missing/stale changes; Software approval and title-risk findings; Issues
finding changes; Sources and Jobs run outcomes. These are required plan work,
not follow-ups. Keep explanations on the owner pages, not Home.

## Goal implementation plan

**Goal:** Refactor Home into a domain overview above Needs attention. Major
Operations areas have meaningful domain-owned totals/KPIs and truthful trends
of at most 30 days wherever existing history supports them. Coverage shows
current status totals without a separate Home trend. Home composes results
without deriving domain state. Keep the detailed client portfolio on Clients.

**Scope:** Home composition and total trends, the Clients portfolio, and the
minimum owner-page changes needed to explain each domain's movement. Preserve
queue/ownership/tenant semantics and PLAN-043's unrelated issue-review edits.
No schema, dependency, external interface, release, commit, push, or deployment.
Testing and performance measurement require explicit user authorization.

**Steps:**
1. Reconcile all touched Home/Clients diffs against current HEAD and retain
   pre-existing user edits. Map each KPI, trend, denominator and drilldown to an
   owner contract. Distinguish current-state totals from historical trends.
2. Extract the selected 30-day contracts above into the smallest domain-owned
   readers; preserve each owner's current population and unavailable behavior.
3. Make Home show supported total trends and current Coverage status counts.
   Keep movement explanations and breakdowns on their owning pages; complete
   those page changes within this plan and link each Home card to its owner.
4. Use only history already owned by each domain. PLAN-019 is complete and its
   first-seen/presence trail is in the current checkout. Record other
   historical-total gaps for review rather than substituting event counts.
5. Review the final diff and permitted documentation/code checks. No tests or
   performance measurements without explicit user authorization; report any
   unmet trend or performance target.

**Affected files (expected):** `operations/apps/core/views.py`,
`operations/templates/home.html`, and only the owner readers/pages needed for
Clients, Computers, Inventory, Patching, Coverage, Software, Issues, Sources,
and Jobs, plus this handoff/blueprint and registry. Confirm the file list after
reconciling existing edits; preserve unrelated work and PLAN-043 changes.

**Validation:** No runtime validation was run. The checkout is at `cdc9c6db`,
matching `origin/master` and `a-m-rose/master`; local work remains uncommitted
and is retained. PLAN-019 completion evidence is reconciled into this checkout.

**Checkpoint / next action (2026-11-06):** Reconciled the Home and owner-page
changes against the worktree. Home puts domain cards before Needs attention,
keeps the detailed client portfolio on Clients, and shows same-definition
30-day total comparisons only for Clients and Inventory. Inventory counts use
admitted source-record subjects, excluding companion observations from both
Home and the owner list. Other cards do not use event counts as trends; the
Needs attention list no longer shows a “new today” subcount. Additional finding
lifecycle and source/job event aggregation reads were removed from Home.
Patching, Coverage, Software, Issues, Sources, and Jobs values use their owner
definitions and link to their owning workflows. Inventory and Patching link to
existing movement evidence; Software already has seven-day title/risk counts
and decision activity; Issues rows show first-seen, last-detected, and closed
times; Sources and Jobs expose run outcomes and histories.

Coverage has current missing/stale counts, Computer drilldowns, and evaluation
freshness, but no historical verdicts. No Coverage history or schema was added.
Whether those current owner details satisfy the movement requirement remains
unresolved. The existing under-two-second Home target and inventory history
query cost are unmeasured. No tests, runtime checks, performance experiments,
or schema changes were run. Changes remain uncommitted; unrelated local work and
PLAN-043 edits in shared files are preserved.

**Next:** resolve the Coverage owner-detail requirement and whether performance
validation is authorized. Do not complete this plan or claim the performance
target until the scope decision and required validation are recorded.

2026-11-04: User directed page-by-page work starting with Home. Review current
Home queries, ownership constraints and prior measurements; identify and test a
bounded improvement preserving displayed counts and freshness. Changes remain
schema-free, with production writes and release separately gated. Other pages
and the existing Computers follow-up remain deferred until selected.

Home checkpoint: the mapping card previously ran the identical independent-action
selection twice for action and distinct-client totals. One aggregate now returns
both from the same selected rows, preserving null-client handling and ownership
filters. This removes one selection execution; its latency impact is unmeasured.
39 focused dashboard, Issues and synthetic PostgreSQL tests pass, including
aggregate parity across covered representatives, clients, statuses and empty
scopes. The prior Home findings-rollup sample timed out after four seconds and
predates PLAN-045; no current handler or browser timing is available. Next measure
the rollup and full handler against a compatible current schema before selecting
another optimization. The earlier navigation/Computers changes remain uncommitted.

Home diagnostic, 2026-11-04: production has the ownership relation, independent
evidence function and recorded migration 0403. One deployed-code, runtime-role,
read-only handler sample canceled the rollup at its four-second SQL limit after
5.88 seconds total; rendering and shared context were not reached. A seven-second
EXPLAIN ANALYZE also timed out while executing the independent-evidence function;
the estimated plan shows a source-record lookup as a per-row subplan. A separate
bounded aggregate found 13,317 eligible source-record findings for 5,073 distinct
subjects. Reusing evidence per subject is a candidate, not yet measured or proved
equivalent; preserve ownership, missing subjects and all aggregate semantics.
The deployed sample does not include the uncommitted Home change. Diagnostic
temporary files were removed. Next compare a deduplicated evidence lookup with
the current query using bounded read-only tests and verify exact aggregate parity.

Follow-up: on one read-only snapshot, both the current rollup and a candidate
evaluating evidence once per distinct subject hit a ten-second SQL limit; neither
returned rows, so parity and speedup are unproven. A second experimental grouping
by the evidence function's source inputs failed immediately because operations_app
cannot read `entity_observation_current`; do not bypass this security boundary.
The organization lookup uses an existing source-instance index, with 7 source
instances and at most 125 active organization records per instance in a separate
aggregate sample. No index benefit is established. Next design a permission-safe
shared evidence interface or projection with PLAN-045, then obtain explicit schema
approval before implementation. Reassess the Home query once that work exists.

## Goal and scope

Improve Operations pages one at a time, starting with Home. Preserve tenant,
ownership, count, filter, URL, and CSV contracts. Home's requirements and
domain-data ownership inventory now precede further experiments or code work.
No schema changes, dependencies, or public-interface changes without review and
authorization. Production reads remain within existing bounded approval.

## Affected files and steps

`apps/core/issue_selection.py`, `context_processors.py`, Computers-only sections
of `views.py`, focused tests, and governance documents. PLAN-043 concurrently
owns issue review in other sections of views.py; preserve those edits. PLAN-012
owns Computer read semantics and its separate verify gate. PLAN-003/004's
selection and source-record contracts remain unchanged.

1. Compare narrower equivalent Issues count query shapes against PLAN-042's
   baseline with bounded read-only SQL. Choose only a measured improvement.
2. Implement the count change and reuse Patching navigation totals with a
   bounded tenant-specific cache. Verify zero caching and expiration behavior.
3. Inspect Computers filtering, pagination and late detail hydration. Bound
   expensive details where membership/card semantics permit; retain complete
   filtered CSV behavior. Measure specific alternatives before changing SQL.
4. Run focused behavioral/PostgreSQL tests, checks, lint and whitespace checks;
   retain aggregate measurements and any unresolved targets.

## Decisions and validation

Baseline evidence: [PLAN-042](../../../docs/records/PLAN-042-page-load-evidence-2026-11-02.md).
Settings 4.60 s (shared context 4.30 s); Computers 10.27 s. A faster count must
select the same representative before excluding covered findings. No stale
zero, reduced count meaning, longer arbitrary TTL, or cross-tenant cache keys.
No fleet performance measurements on the workstation; use small synthetic
PostgreSQL fixtures there and bounded approved production reads for timings.

## Checkpoint and next action

Implemented locally: covered-only aggregate state joins (full join for related
scopes), tenant-keyed 60 s Patching badge reuse, compact Hudu membership,
narrower existing source-record count reader, and deferred age/search/tooltip
work. No schema, authority or public-interface change. Patching counts can lag
by up to 60 seconds, matching the existing Issues bound.

52 focused checks and 8 synthetic PostgreSQL tests pass; Django, compilation,
registry and whitespace checks pass. Existing lint/format limits, query trials,
packaging review and aggregate evidence are in the
[validation record](../../../docs/records/PLAN-044-page-performance-validation-2026-11-02.md).
Final isolated handler comparison: Settings 5.6225→2.0111 s (repeat
0.2028→0.0361); Computers 12.6412→6.9918 s. Badge and rendered-context parity
passed on one snapshot. Cache/load-confounded handler samples are not browser
timings or a deployed release. Temporary remote files and local testcontainer
were removed. Unrelated concurrent PLAN-043 edits/commit remain preserved.

Resume gate: review local changes before separately approved commit/release;
deployment/browser verification remains pending. Computers still misses the
two-second target. Broader summary/page-selection design and other routes are
in Operations TODO, not silently accepted as performance exceptions.

## Deferred follow-up: remaining page performance

Design a cheaper fleet-summary and filter pass with page-first detail selection,
preserving card, filter, CSV population and source-authority semantics. The
last local candidate still took 6.99 seconds for Computers, and the cold Issues
badge count took about 1.7 seconds. Dashboard, Clients, Issues, Sources,
Software and Source Records retain the separate PLAN-042 measurements. Measure
alternatives before proposing storage or index changes; this follow-up remains
in Operations TODO and is not part of the first implementation slice.

2026-11-04 continuation at HEAD `6f9a3a53`: reviewed the local slice against
PLAN-045 ownership readers and PLAN-047–050. PLAN-048's proposed typed reported
facts may change these read costs; existing timing evidence predates current HEAD.
Updated the synthetic Issues SQL fixture for the current ownership relations and
independent-evidence function. Navigation/coverage tests: 31 passed; PostgreSQL
selection tests: 8 passed; Django system check, focused test lint, registry and
diff whitespace checks passed. A broader Computer-read/Issues run had 31 passes
and three source-text assertion failures in `test_computer_reads.py` after
PLAN-045 changed the relevant dashboard and patching selectors. Those failures
need reconciliation with PLAN-045; they are not evidence of PLAN-044 parity.
No current-HEAD fleet timings or browser verification were performed. Next,
measure a compatible summary/page-selection alternative against current code
and coordinate with PLAN-045/048 before changing fleet-wide behavior.

2026-11-06 Coverage movement review: `device_requirement_state` is replaced
on each evaluator pass and is explicitly derived/rebuildable. Its drift table
records evaluator disagreements only, not Coverage changes. Missing/stale
findings retain condition-level episodes, but they are not Computer-level
Coverage snapshots: a requirement can change missing↔stale, scope can change,
and evaluator reconciliation may retain findings while collection/lifecycle
evidence is blocked. `closed_at` is not backfilled for pre-0.62 rows, and a
reopened condition reuses an active finding row after resolution. The findings
change-history trigger captures row changes, but that still represents finding
episodes (including operator state), not a historical Coverage total. Therefore
existing data cannot support an exact Coverage trend or count of Computers
moving in/out of coverage. Recommendation: keep Coverage movement off the page
under the no-schema constraint; retain current missing/stale counts, freshness,
and Computer drilldowns. Do not add a proxy activity count.

2026-11-06 Home card review: owner totals/KPIs and the two supported total
trends match the agreed scope. Rendered Coverage's meeting/not-meeting pair in
green/red and clarified that the Software risk KPI counts titles. Values still
come from the domain owners. `git diff --check` passed.

2026-11-06 static Home read-path review: each area summary is delegated to its
current owner. Issues separately reads open/paused totals, the critical mapping
alert, and prioritized attention items. Those are distinct selections with
different semantics; combining them without performance evidence could obscure
Issues selection behavior and add query complexity. No query changes were made.
The under-two-second target remains unverified because no rehearsal or
production-copy target is configured in the available private profiles. Home
requirements and presentation are complete; separate Computers work remains.

2026-11-06 authorized Home validation: `manage.py check`, Home template loading,
and focused Ruff checks passed. Updated the stale `test_dashboard.py` with
approval to exercise the current Home composition and rendering; together with
`test_navigation_counts.py`, 9 focused tests pass. `git diff --check` passed.
No performance measurement was run because the available external profiles are
not identified as an approved rehearsal or production copy; local measurement
is prohibited. Next: identify an approved measurement target before measuring
the under-two-second goal.

2026-11-09 goal update: target is 1.5 seconds, with 2.0 seconds as the hard
maximum. The user authorized autonomous work through achievement, including
commit and push as needed. Reconciled the SSH profile read-only: the host runs
Ninja Operations and Postgres alongside production-labeled services, so it is
not an isolated rehearsal target and will not be benchmarked. Available HTTP
profiles do not identify an app rehearsal. Next: inspect the query path and
make only evidence-based, design-preserving fixes while locating a safe
measurement environment. Before an origin push, review the automatic deployment
effect and pending migration set as required by repository policy.

2026-11-09 static request-path finding: the global `brand` context processor
loads the full active-client roster on every authenticated request. Home has no
client selector or portfolio table, and its template does not consume that
roster. Skip this query for the Home route only; retain the existing client
choices on other pages. This is a bounded request-path reduction with no data,
schema, or UI change. Validate via a focused context-processor test.

Static inspection also found Home loads `device_status` policy for Computers
and Patching independently. Pass the same owner-provided policy to the Patching
summary so Home avoids a duplicate policy query without moving or changing
policy semantics.

The staff-only Jobs card called the complete Admin health audit (health,
definition versions, schedules, resource limits, and runtimes) but displayed
only job counts and scheduler/worker heartbeats. Narrow the Home summary to the
two existing Jobs diagnostics it consumes; keep the full audit on Admin pages.

2026-11-09 Home roster reduction: `brand()` now skips the unused client roster
on the Home route while retaining it elsewhere. The focused test verifies both
branches. `manage.py check`, 11 Home/navigation tests, Ruff on changed code
(ignoring the existing PLR0911 in `_active_section`), formatting, and
`git diff --check` pass. No page timing was taken. Next: review the total diff,
isolate the Home commit from existing PLAN-043 work, and identify a designated
measurement environment before timing.

The Computer and Patching summaries also now share Home's single
`device_status` policy read. The Home composition test verifies the same policy
object reaches the Patching owner; its default policy lookup remains available
for other callers. The static changes remove the unused Home client-roster read
and one duplicate settings read. They are not evidence of meeting the latency
target.

The Home Jobs summary now reads only the existing health and runtime
diagnostics it displays; the Admin health audit remains unchanged. `manage.py
check`, 12 focused Home/navigation tests, targeted Ruff checks, plan-registry
validation, and `git diff --check` pass. No response-time measurement has been
run. These query reductions are static improvements and do not establish that
Home meets the latency target.

2026-11-09 checkpoint: the active target remains ordinary Home ≤1.5 seconds,
with 2.0 seconds as the hard maximum. Live production measurement, focused
development, commit and push are authorized. Commit `9f3769a9` is on both
remotes and deployed. Operations is healthy; startup reported no pending
migrations.

The authenticated deployed Home request exceeded its five-second client wait
and later returned 500 because `mapping_query()` referenced an undefined
`groups` name. Its Issues aggregate remained active about 98 seconds. Read-only
production EXPLAIN estimated 63,144 rows through a wide window step. Home had
four separate Issues selections for totals, mapping counts, and attention. The
first combined compact selection still timed out at five seconds and its window
query remained active for 108 seconds; that abandoned read was canceled.

The local revision removes Home's global ranking window. The documented shared
action keys are limited to `unmatched_source_group` and
`client_unattached_group`; only those rows need `DISTINCT ON`, with the same
admin-first representative ordering and covered-item filtering as the shared
Issues selector. Other Home items have unique `finding:<id>` keys. Home derives
totals, mapping counts, and attention groups from this one owner selection.
However, that query still ran over 108 seconds. Production EXPLAIN showed the
device ownership condition invoking a sequential scan of all 5,718 ownership
rows for each finding. The current local fix materializes the tenant's resolved
ownership rows once and joins by device/client, preserving the same states and
attribution. The `mapping_query()` name is fixed. Python compilation, targeted
Ruff, plan-registry, and whitespace checks pass; no tests were run. No migration
or schema change is involved.

Inventory's separate current/freshness and historical total reads measured
0.80 seconds versus 1.54 seconds combined with exact parity in one repeatable
production snapshot. This is component evidence, not a Home timing. **Next:**
review, commit and push the ownership-join fix, then time one bounded ordinary
Home request in production. Continue until ≤1.5 seconds is demonstrated, with
2.0 seconds as the hard maximum.

2026-11-09 follow-up: `9fab308d` was committed, pushed to both remotes and
deployed. Its bounded authenticated Home request still exceeded five seconds;
the matching database statement was canceled. Read-only EXPLAIN estimates
63,144 rows through the compact selection and identifies a repeated source
record attribution subplan. Active source-record findings have 13,327 findings
across 5,071 distinct records. The local Home-only query now materializes that
attribution once per distinct eligible source record; other Issues callers are
unchanged. This reduces function calls by 8,256 in the observed active set.
The production request, diagnostics and cancellation ran under the recorded
authorization. Next: validate and release this focused change, then retry one
bounded Home request; cancel only its own active statement if the five-second
cap expires.
