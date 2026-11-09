# PLAN-044 — Navigation and Computers performance

Status: active. The Patching outcome summary below supersedes the earlier no-schema restriction for that change. Home target: ≤1.5 seconds, with an ordinary response under 2 seconds required. Migration 0406 is already applied. Commit and push approvals remain separate; an origin push approval must include automatic deployment and reviewed pending migrations.

## Patching outcome summary — 2026-11-09

The user authorized implementing the Patching summary after the live query took
6.814 seconds. This supersedes the no-additional-schema restriction for this
Patching change only. SQL migration `119_patch_outcome_counts` builds counts by
device, exact outcome timestamp, and status, then maintains them transactionally
from patch-fact changes. Home retains its existing ownership and scope logic and
uses the same exact rolling cutoff. The reader falls back to patch facts while
the independently started ingest service has not yet applied the migration.

The initial migration locks patch-fact writes while it scans and populates the
summary; its production duration, storage, write overhead, concurrency behavior,
and actual speedup are unmeasured. Review those deployment risks and the pending
migration before seeking push approval. The timestamp-level grouping may not
reduce every workload sufficiently. This change addresses only Patching; the
other measured slow Home readers remain. Existing refresh and ingestion state is
not a guarantee of external source freshness.

Read-only production preflight: 11,047 recent outcome rows form 6,560 summary
groups. This establishes some reduction for the 30-day population, not query
speed or total table size. The ingest ledger is current through 118 and Django
reports no pending migrations; SQL 119 is the pending change in this release.

Validation: a small throwaway PostgreSQL database applied the migration and
confirmed summary parity after inserts, status/type/timestamp updates, and
deletion. Python compilation, plan-registry validation, and diff whitespace
checks passed. No production change or performance measurement was performed.

## Home implementation plan — 2026-11-09 review

### Goal and scope

Make the complete authenticated Home request meet the latency target while
retaining the domain overview, supported trends, attention list, known-client
impact counts, and source/job status. Home composes owner results. Client impact
counts distinct clients associated with the selected issues; evaluation maintains
those associations. Home does not re-prove source ownership to display this KPI.
Tenant isolation and current ownership checks for client-scoped access and writes
remain required; the reporting count does not replace those checks.

This is a plan for scoped edits to existing owners. No new summary framework,
table, function version, dependency, or blanket cache is proposed. An additional
migration or data-model change requires a concrete proposal and approval. Do not
edit applied migration 0406. PLAN-049's independent index work retains 0407+;
this plan does not reserve another migration number. Coordinate any ingest
publication changes with PLAN-054's source/findings lock-order work.

### KPI contract to preserve

| Area | Home values |
| --- | --- |
| Clients | Active total and supported 30-day comparison; portfolio detail stays on Clients. |
| Computers | Current total, active, needs review, retired. |
| Inventory | Present source-record total, same-population 30-day comparison, latest-report freshness. |
| Data collection | Open collection actions, with paused actions as secondary context. |
| Patching | In-scope/excluded/unmanaged counts; actively patching count and percentage; 30-day installed/failed patch outcomes for in-scope machines. Percentage denominator is all current Computers; numerator uses the owner's active, in-scope, recent-activity rule. Outcomes count patches, not Computers. |
| Coverage | Meeting/missing pair, stale separately, neutral separately, exemptions handled by the owner, evaluation freshness. No Coverage trend or new history. |
| Software | Distinct installed titles, owner-defined approval breakdown, distinct installed titles with active title-linked risk findings. Verify that the "approved" label follows effective Software decisions/policy. |
| Issues | Open independent actions, critical actions, paused secondary context; prioritized attention and critical mapping alert retain known-client impact counts. |
| Sources and Jobs | Current source freshness and job processing status in the shared footer; staff cards reuse those results. |

Retain the existing attention ordering unless review identifies a separate
correctness issue. Unknown client attribution is not proof of no impact. Do not
silently substitute raw finding counts for independent actions, remove KPIs to
meet latency, or change a domain population to match an easier query.

### Confirmed checkpoint and evidence

At the design review, HEAD and both local remote-tracking tips were `e9439cc5`.
A production read of the migration ledger confirmed 0406 applied. Earlier notes calling that commit
local-only or awaiting its migration deployment are superseded.

The complete static review covered Home composition, every feeder's SQL and
supporting views, tenant/session/authentication middleware, navigation context,
and Home/base templates. Templates have no follow-up data fetches or external
script/style dependencies. Summaries execute sequentially. Navigation Issues
and Patching counts have separate 60-second process-local caches.

One read-only sample per feeder used the deployed Django readers/runtime role
with a 3-second statement cap; each feeder used its own transaction:

| Feeder | Elapsed | Evidence |
| --- | --- | --- |
| Device policy | 0.111 s | Includes initial database connection; SQL itself 0.015 s. |
| Clients | 0.010 s | Current and historical aggregate. |
| Computers | 0.149 s | Lifecycle and current/activity reads. |
| Inventory | 1.328 s | Current/freshness SELECT 0.641 s; history SELECT 0.679 s. |
| Issues | >3 s | Statement canceled by its timeout. |
| Patching | >3 s | Independent statement timeout. |
| Coverage | 0.110 s | Stored verdict aggregation. |
| Software | >3 s | Independent statement timeout. |
| Sources | 0.243 s | Latest source-run/success selection. |
| Jobs | 0.103 s | Health and runtime diagnostics. |
| Navigation Issues, cold | SQL error | SQLSTATE 42P01: source_client alias referenced without its join. |
| Navigation Patching, cold | 0.292 s | Separate active-finding count. |

These samples are not a summed page baseline. No full HTTP/browser success or
under-two-second result is established. Session/authentication/network costs
were not isolated. An empty-context template initialization sample is not a
representative full render and is excluded from the latency budget.

Read-only EXPLAIN estimates identify JIT in Issues and Software, a substantial
source-link selection in Patching, and live installation/title grouping in
Software; estimates do not prove where elapsed time is spent. Existing Software
title rollup lacks lifecycle invalidation and cannot simply replace live counts.

The deployed attribution helper plus input selection separately measured 1.789 s
for 5,072 observations. The earlier 4.09 s sum of six chunks repeats work and
must not be treated as a single full-helper timing. Diagnostic execution of the
equivalent helper body found 191 groups and 171 scalar name proofs; proof work
was roughly 0.15 s. This does not justify another proof-function rewrite.

### Ordered implementation

1. **Audit and repair stored issue-client publication.** Trace the existing
   finding client IDs used by the selected action population. Source-record
   evaluation already computes independent evidence and supplies client_id to
   publication. Its open/acknowledged upsert refreshes that ID; its
   investigating/suppressed update refreshes details/timestamps but omits it.
   Repair that maintenance gap while preserving operator status and snooze.
   Check existing reassessment/invalidation on mapping changes and unknown
   attribution. Surface a concrete uncovered path before expanding scope; do
   not label stale association as current or fall back to an inherited
   observation client. Keep current-access ownership guards intact.
2. **Simplify Issues aggregation and repair navigation.** Keep one shared
   independent-action definition, including covered representatives, shared
   action keys, pending candidates, severity, and pause rules. Home counts
   distinct recorded client associations from those selected actions instead
   of invoking the bulk ownership proof. Remove attribution CTEs made obsolete
   by this change; retain the applied database helper for compatibility.
   Repair the ordinary selector's missing source_client alias. Supply Home's
   already computed open-action total to navigation through request context,
   preserving the standalone cached badge path for other pages. Keep Patching's
   badge definition separate unless parity with a Home count is demonstrated.
3. **Narrow Patching in its owner.** Reconcile the denominator: the current
   query begins with resolved owners, whereas the KPI denominator is all current
   Computers. Preserve ownership restrictions for the numerator and outcomes;
   explain unresolved scope rather than classifying it as unmanaged by default.
   Inspect the source-link/activity/outcome plan, restrict inputs to the required
   population and time windows, and reuse existing domain projections where
   their meaning matches. Preserve counts across multiple links and patch facts.
4. **Narrow Software in its owner.** Confirm the title population and approval
   meaning against the Software page and effective decisions, including publisher
   decisions. Then remove unnecessary installation-level work from title-level
   aggregation where equivalent. Preserve distinct title risk counting and
   lifecycle/stale-installation exclusions. Do not replace live reads with the
   existing lifecycle-insensitive rollup. Propose any genuinely missing domain
   state separately instead of adding another Home-specific abstraction.
5. **Reduce Inventory read cost.** Keep the agreed admitted-record population,
   current presence, reporting freshness, and exact 30-day comparison. Inspect
   the metadata and historical joins for unnecessary work; reuse the existing
   history and owner reader. Do not substitute run/event counts for a trend or
   add snapshots without review. Leave the already inexpensive owner readers
   alone unless new evidence identifies a correctness problem.
6. **Validate and release the reviewed changes.** Check the final runtime file
   and packaging list; run the small existing checks below. Prepare a concrete
   diff and list any pending migrations before separate commit/push approvals.
   An approved origin push triggers Portainer automatically; push the secondary
   mirror afterward, with no separate redeploy. Verify deployment and measure
   the complete authenticated request using the approved bounded diagnostics.
   If a rehearsal is available, measure there before release. If the target is
   still missed, identify the remaining feeder before proposing another change.

### Affected files

- `operations/apps/core/issue_selection.py`, `context_processors.py`, and
  `views.py`: action aggregation, navigation reuse, and composition.
- `ingest/source_records.py`: issue-client publication maintenance.
- `operations/apps/core/patching_reads.py`, `software_review.py`, and
  `source_record_views.py`: domain-owned read reductions and KPI correctness.
- `operations/templates/home.html` only if a reviewed label/freshness correction
  is needed; no layout rewrite is planned.
- This handoff, module/root blueprints, and plan registry for continuity.
  Existing focused test files only when needed and authorized; no broad suite
  or speculative new test files.

### Implementation checkpoint

The scoped readers and publication updates are in the worktree. Small synthetic
PostgreSQL checks exercised the complete Home Issues aggregation, ordinary/Home
selection parity, recorded-client batch refresh and publication for investigating
and suppressed episodes with preserved status and snooze, the Patching population and activity window, Inventory history parity, and Software
title/publisher and risk parity. A non-superuser tenant-RLS fixture and a stale
recorded-client fixture checked tenant and current client-scoped Issues access.
The Home navigation zero and standalone fallback paths were checked separately. These functional checks do not establish a response
time or production behavior. Existing Issues fixtures need updates to cover the
new behavior; the user requested no further testing. Source-record client
associations can lag while queued reassessment is pending and are labeled recorded.
Software's existing owner status treats the absence of a matching prompt or reject
finding and investigate decision as its default bucket, so Home describes that
bucket as having no open decision issue rather than claiming explicit approval.
Patching reports unresolved ownership separately from unmanaged scope.

A shared source-group action can contain both an unmatched and an unattached
finding. Issues filters by type before picking a representative; Home formerly
picked one representative across types, so an attention count could differ from
its type-filtered link. The attention rows now select representatives per type,
while overall action totals still deduplicate across types. The same action may
therefore appear in both relevant attention rows; each row matches its drilldown.
Critical, category-critical and critical-mapping totals likewise filter severity
and mapping type before selecting representatives, matching Issues scopes even
when records representing one action have different severities. A synthetic
PostgreSQL check also confirms that a covered selected representative stays
excluded instead of exposing its uncovered sibling.

### Acceptance evidence and remaining gates

2026-11-09 production measurement: the deployed Issues, Patching, Software,
and Home view files match `60ba6e45`. A staff/superuser authenticated Home GET
returned HTTP 200 in 14.440 seconds (navigation cache state unknown), missing
the target. Separate read-only reader samples measured Inventory at 2.635 s,
Issues at 3.845 s, and Software at 3.345 s; Patching hit a five-second SQL
statement timeout after 5.015 s. These independent samples are not a breakdown
of the measured request. The full request was measured on the internal service
endpoint and does not include browser or external network time.

Follow-up bounded read-only production measurements: Inventory's two queries
were 0.806 and 0.833 s; Issues' main query was 2.675 s; Patching was 6.814 s;
Software was 2.634 s. Separate `EXPLAIN ANALYZE` executions measured Patching
at 6.395 s with a patch-facts bitmap scan repeated 2,783 times; Issues at
2.870 s with temporary reads/writes during aggregation; Software at 2.714 s
with temporary reads/writes and large grouped/sorted installation inputs;
Inventory's current and history queries at 0.508 and 0.626 s with substantial
shared block reads, including a history sequential scan. These are individual
samples under live load; execution-plan node times are inclusive and cannot be
added. No application code was changed.

| Requirement | Current evidence | Remaining |
| --- | --- | --- |
| Stored issue clients and access | Synthetic PostgreSQL checks cover changed/null associations, status and snooze preservation, tenant RLS and current client-scoped source evidence. Mapping changes enqueue reassessment. | Associations can lag while reassessment is pending; existing regression coverage is incomplete; the user requested no further testing. |
| Issues and navigation | Synthetic checks cover representative parity, type and severity drilldowns, recorded-client counts, zero reuse and cold fallback. | Existing Issues fixture and obsolete batch-query assertion remain outdated; no further testing was requested. |
| Patching | Synthetic checks cover all-current denominator, unresolved ownership, duplicate links, activity window and outcomes. | Measure the owner reader in an authorized environment. |
| Software | Synthetic parity covers modal-publisher ties/nulls, lifecycle, title decisions, publisher investigation and title-linked risk. | Measure the owner reader in an authorized environment; the owner's default bucket is not proof of explicit approval. |
| Inventory | Synthetic history parity covers duplicate and expired history and tenant scope; current/freshness population remains unchanged. | Measure the owner reader in an authorized environment. |
| Release and end-to-end latency | Runtime files are included in the Docker build; no new migration is proposed. Django check and 55 existing focused tests pass. | Review remaining pending migrations before separately approved commit and push; verify deployment and a bounded authenticated request in an authorized environment. The response-time target remains unproven. |

### Validation and completion

Keep testing light: reuse relevant existing Home/navigation/Issues and
source-publication checks; exercise only the cases changed. Confirm distinct
clients across repeated issues, null/changed clients, preserved investigating
status, independent-action parity, cold navigation, patch denominator, and
distinct software titles. If existing checks cannot cover a material gap,
describe it and obtain approval before adding/changing test coverage. Earlier
0406 tests do not validate these proposed fixes; the previously observed stale
Issues source-text assertion must be reported or reconciled within scope.

Run applicable Django checks, changed-file syntax/lint, plan-registry validation,
and git diff --check. Use only small synthetic/local functional checks; no local
performance runs or full-fleet producer passes. Production diagnostics remain
read-only and bounded; cancel only the identified diagnostic statement if its
client disconnects. Do not treat a timeout as a measured completion time.

Completion requires matching displayed counts/drilldowns, preserved tenant and
ownership protections, healthy deployed services after an approved release, and
a successful complete authenticated Home response under 2 seconds (target
≤1.5 seconds), including a cold navigation-cache path. Component timings and
estimated plans alone cannot close the plan. Record permission level, cache
state, response status, timing, and limitations; do not promise load capacity
from a single request.

**Current next action:** Continue the implementation and validation recorded in
the [Operations checkpoint](../../BLUEPRINT.md). Historical notes below retain prior scope and evidence; their old
next-action/approval statements do not override this checkpoint.

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

2026-11-09 follow-up release: `599dc916` is on `origin/master` and
`a-m-rose/master`; origin deployment started automatically. Operations is
healthy and serves the new source-record CTE. The authenticated Home request
still exceeded five seconds, and its matching statement was canceled. EXPLAIN
estimated total cost fell from 566,147 to 121,907; this remains estimate-only
and does not satisfy the latency target. A read-only count found 13,327 active
source-record findings across 5,071 records, all uncovered. The runtime role
cannot read `entity_observation_current` directly, so further set-based
attribution would need a separately reviewed security-definer/database design.
No migration is pending from this change. **Next:** inspect remaining query
costs within the no-schema scope before authorizing another production change;
the ≤1.5-second goal remains unverified and unmet.

2026-11-09 bottleneck check: a production sample of 40 distinct active source
records called `computer_client_independent_evidence` 40 times in 0.538 seconds;
38 results had a client. The active population contains 5,071 distinct source
records, so the current per-record path is the remaining performance blocker.
The app role cannot read the protected observation tables directly; preserving
the evidence rules while batching requires a tenant-checked security-definer
database function and migration. The user authorized this additive function and
focused tests on 2026-11-09; production push/deployment authorization remains
separate. PLAN-049's old migration 0406 must move to 0407 or later because this
plan now owns 0406 after PLAN-055's 0405.

2026-11-09 implementation: migration 0406 adds a tenant-checked
security-definer batch function. It resolves current source observations and
group identities in sets, deduplicates complete identities before link proof,
and retains the scalar function for other callers. Home passes its distinct
observation IDs to the batch function. Focused PostgreSQL tests cover direct
instance clients, operator and automatic mapping evidence, stale/unproved or
ambiguous mappings, duplicate input, tenant guard and grants; all three pass.
The existing Issues suite also has one unrelated source-text assertion failure
against unchanged `views.py`. Django checks pass; migration parity reports no
model changes. No production push has been approved for migration 0406.
Commit `e9439cc5` is local only. **Next:** obtain explicit approval for an
origin push including migration 0406 and its automatic Portainer deployment.
After approval, measure one bounded Home GET.
