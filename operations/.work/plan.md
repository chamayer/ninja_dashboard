# Issues queue operator model and coverage correction

## Status

**Default Issues-page performance correction in progress.** This supersedes the
completed taxonomy rollout plan. The active taxonomy remains five Categories,
34 Types, and 53 Issues. This work changes the operator projection, count
semantics, assessment coverage, and Issues-page layout; it does not rename
internal condition keys or alter the approved taxonomy.

Repository baseline: `120d641` is current local and remote `master`.
Pre-existing untracked `.work/probe_*` and bootstrap files are unrelated and
must remain untouched. Production deployment of this exact baseline has not
been independently reverified in this checkpoint.

## Goal

Create one understandable operator work queue that:

- never makes retained findings appear to have disappeared;
- distinguishes work needing action from work blocked by another condition or
  pending current information;
- keeps software policy decisions out of Issues;
- exposes every nonempty Issue group before result pagination;
- filters and sorts the complete matching dataset;
- hides engine internals from operators while retaining administrator
  diagnostics; and
- remains visually compact enough for routine use.

## Confirmed baseline

The latest read-only production review found:

| Category | Retained | Needs action | Blocked | Pending |
| --- | ---: | ---: | ---: | ---: |
| Inventory | 2,713 | 39 | 0 | 2,674 |
| Agents & reporting | 4,239 | 0 | 127 | 4,112 |
| Software & security | 12,002 | 0 | 0 | 12,002 |
| Patching & support | 3,710 | 2,912 | 61 | 737 |
| Data collection | 7 | 0 | 0 | 7 |

There were 22,671 retained unresolved Issues: 2,951 needing action, 188
blocked, and 19,532 pending. Another 1,799 active software policy
candidates belonged in Software Decisions. There were 445,919 resolved
historical findings.

Fresh assessment coverage was incomplete: 2,480 Inventory, 1,303 Agents &
reporting, all 12,002 Software & security, 695 Patching & support, and all
seven Data collection findings lacked a fresh active-policy assessment. These
findings were retained, not deleted. Their absence from actionable-only cards
is both an assessment-coverage and presentation defect.

At verification time, `conditions-taxonomy-4` was active and valid, all 53
conditions were mapped exactly once, 6,410 current assessments existed, and
all 6,359 required non-context participants represented by those assessments
had coverage.

## Approved operator vocabulary

Do not expose **Response**, **Actionable**, **Unknown**, **Assessment
disposition**, or **All retained** as operator terminology.

Summary labels:

- **Unresolved**
- **Needs action**
- **Blocked**
- **Pending**
- **Paused**
- **Software decisions**

Filters:

- **Status:** Open, Acknowledged, Paused, Resolved
- **Attention:** All, Needs action, Blocked, Pending

`Paused` is an operator status, not an engine attention result. Internal
policy values remain available for execution, audit, and diagnostics but map
to the operator model as follows:

| Internal outcome | Operator presentation |
| --- | --- |
| Complete, current, and permitted | Needs action |
| A prerequisite or overriding condition prevents useful action | Blocked |
| Missing, stale, incomplete, or unknown evidence/assessment | Pending |
| Future snooze set by an operator | Paused status |

Rows outside Needs action show one short reason, such as “Identity
unresolved,” “Computer offline,” “Source unavailable,” or “Patch data
incomplete.” Explanations must not become long state labels.

## Count contract

### Unfiltered fleet summary

The top row contains exactly six compact clickable cards using the approved
summary labels. It is fleet-wide and never changes with filters below it.

For unresolved Issues, excluding Software Decisions:

`Unresolved = Needs action + Blocked + Pending + Paused`

- **Unresolved:** open or acknowledged Issues, including paused Issues.
- **Needs action:** unresolved, not paused, with a current complete assessment
  permitting action.
- **Blocked:** unresolved, not paused, with a current assessment identifying a
  prerequisite or overriding condition.
- **Pending:** unresolved, not paused, with no current complete decision.
- **Paused:** unresolved with an active operator snooze.
- **Software decisions:** active policy candidates in their separate workflow
  and never included in the other five cards.

Every card links to its complete population. Counts use one captured
scope/time and must satisfy the conservation rule.

### Filtered workspace

Everything below a clear **Filtered results** boundary follows selected
filters. Its compact summary contains only matching issue rows, affected
Computers, affected clients, and the selected Status/Attention scope.

Category and Type headers show both current matches and unresolved totals when
the Attention filter would otherwise make a nonempty group look empty.
Actionable-only Category cards must not serve as inventory totals.

## Work packages

### WP1 - Reconcile the baseline and freeze behavior

- Preserve unrelated user work and compare `27d59cc` with this contract.
- Capture counts by condition, Category, Type, Status, Attention, severity,
  snooze state, and Software Decisions membership.
- Add failing behavior tests for terminology, count conservation, complete
  group visibility, dataset-wide sorting, and filter clearing.

Exit: reproducible baseline and tests demonstrating each current defect.

### WP2 - Create one operator-state projection

- Add one shared projection mapping internal assessments and operator handling
  into Status, Attention, and a short human reason.
- Keep Status, Attention, and Severity independent.
- Map unresolved findings lacking a fresh complete assessment to Pending;
  never hide them or treat them as actionable.
- Use the projection in cards, filters, groups, rows, CSVs, Computer links, and
  count queries.
- Retain technical values only for policy execution, audit, and admin views.

Exit: every unresolved Issue has exactly one Attention state and counts
conserve.

### WP3 - Restore complete assessment coverage

- Build a 53-condition ownership matrix: finding producer, assessment
  producer, participants, evidence, freshness authority, reevaluation trigger,
  and recovery authority.
- Reassess retained findings when source collection succeeds, evidence or
  participants change, policy changes, or freshness expires.
- Add safe backlog reconciliation that does not recreate findings, alter
  operator handling, or clear findings without current type-specific recovery
  evidence.
- Fail closed when required source coverage is unhealthy.
- Expose missing/stale assessment counts in admin diagnostics.

Exit: every eligible retained finding has a fresh assessment or a specific
observable coverage reason.

### WP4 - Separate Software Decisions

- Exclude policy candidates from Issues tables, groups, totals, CSVs, bulk
  actions, and the Unresolved count.
- Make `/software/decisions/` their sole queue and card destination.
- Link relevant Computer and software-detail surfaces to that workflow.
- Keep vulnerabilities, malicious software, unsupported software, protection
  conflicts, and other genuine incidents in Issues.

Exit: each software finding belongs to exactly one workflow.

### WP5 - Simplify the page

Use four visual zones only:

1. Page title and exports.
2. Six-card unfiltered fleet summary.
3. Filtered results controls and compact result summary.
4. Hierarchical grouped results.

Remove duplicate Category tiles, repeated summaries, separate table-filter
cards, policy explanations, severity mini-dashboards, and competing counts.

Primary filters: Category, Type, Issue, Attention.

Secondary **More filters**: Status, Severity, Client, Platform, Online state,
Search. Category -> Type -> Issue remains dependent and defaults to All.

Exit: the page reads top-to-bottom without knowledge of the condition engine.

### WP6 - Make every Issue group visible

- Render five stable Category headings and every nonempty Type as a collapsed
  header before finding pagination.
- Show current matching and unresolved counts on Type headers.
- Keep empty Types in the Type filter without cluttering the group list.
- Expand the selected Type and paginate only its findings; never paginate the
  group-header list.
- Open the relevant group for Type/Issue filters and Computer/evidence
  drilldowns; keep the general queue collapsed.
- Remove duplicate group-navigation cards and duplicate table group headers.
- Ensure sorting cannot hide rows or remove expansion controls.

Exit: all nonempty groups remain discoverable regardless of finding volume.

### WP7 - Make table filtering and sorting dataset-wide

- Keep scope filters above the table; put value filters under the corresponding
  headers for Severity, Finding, Subject, Evidence, Context, Status, and date.
- Provide Apply and **Clear**; Clear removes all `table_*` parameters while
  preserving scope filters.
- Filter and sort the complete selected group before pagination.
- Use database-backed expressions and deterministic ID ordering; do not sort
  only one page or materialize the whole queue with per-row queries.
- Bulk-load identity candidates, source links, device context, and assessments.
- Make filtered counts, pagination, HTML, and CSV share one query contract.

Exit: behavior remains correct beyond 500 rows, totals match rows, and Clear
works.

### WP8 - Hide internals and complete admin diagnostics

Remove from operator HTML and CSV:

- assessment disposition;
- policy/taxonomy version and digest;
- participant or device scope internals;
- rule names, internal blockers, and policy reasoning;
- reevaluation keys and coverage implementation details.

The administrator-only Conditions/Platform Health surface retains:

- condition key and finding ID;
- policy version and digest validity;
- participants and scopes;
- raw disposition, rules, blockers, and reasoning;
- producer, assessment age, and coverage;
- retained/fresh/missing counts for all 53 conditions; and
- links to the operator finding and relevant evidence.

Exit: operators see concise state and evidence; administrators retain complete
auditability.

## Required regressions

- Sorting must not suppress headers while leaving rows hidden.
- Clear must remove every `table_*` parameter.
- Table filters must update matching totals.
- Nonempty Categories must not appear empty because cards count only actionable
  work.
- Software Decisions must not inflate Issues.
- Static string-presence tests are insufficient; request/behavior tests are
  required.

## Expected files

- `operations/apps/core/views.py`
- `operations/templates/findings_queue.html`
- `operations/apps/core/conditions/live.py` or a focused projection module
- `operations/apps/core/tests/test_findings_queue.py`
- condition/evaluator producers and tests identified by WP3
- `ingest/evaluator.py` and source-specific producers where required
- admin condition-health views/templates/tests
- an Operations decision record for the durable state/count contract
- root `VERSION` and `CHANGELOG.md` only for an approved release

Do not add a migration unless a durable schema or measured index need is
demonstrated. Any migration requires explicit review before push/deployment.

## Validation

- Behavioral tests for Status/Attention mapping and short reasons.
- Conservation tests for all five unresolved states.
- Complete 5-Category/34-Type/53-Issue coverage.
- A greater-than-500-row fixture proving every group header remains visible.
- Dataset-wide sorting, filtering, pagination, and Clear behavior.
- Software Decisions exclusion and no double counting.
- HTML/CSV proof that operator surfaces contain no engine internals.
- Admin permission and diagnostic coverage tests.
- Producer reconciliation tests, including unhealthy-source and zero-emission
  recovery cases.
- Query-count checks and representative PostgreSQL performance review.
- `manage.py check`, migration drift/plan review, targeted Ruff/compilation,
  focused Operations and ingest tests, and `git diff --check`.
- Read-only production reconciliation after deployment: card conservation,
  Category/Type totals, assessment coverage, links/CSVs, and service health.

## Out of scope

- Renaming internal condition keys or changing the approved taxonomy.
- Deleting or rewriting retained or resolved findings.
- Changing severity predicates merely to improve displayed counts.
- A general operator policy/rule editor.
- Production jobs, activation, migrations, deployment, commit, or push without
  their separately required authorization.

## Checkpoint and next action

The operator vocabulary, count contract, and target information architecture
are approved in this plan. Local implementation is complete from `120d641`.

Implemented locally so far: the shared operator Status/Attention/reason
projection; six conserved Issues summary cards; retained unresolved findings
visible by default; primary and secondary filters; dataset-wide column Clear;
complete Category/Type navigation before row pagination; operator-safe row
and CSV state; Software Decisions exclusion/link routing; and administrator
fresh-assessment coverage counts. The administrator coverage query now keys
retained rows by condition_key and links each condition to its filtered Issues
view. Evaluator coverage records measured platform and servicing scopes, uses
Ready signals for measured evidence, and writes fresh recovery assessments
before resolving absent findings. ADR-0023 records the durable operator
state/count contract. The operator vocabulary is now Pending (not Awaiting
data), and group headers expose Needs action, Blocked, and Pending counts with
visible per-state controls. Blocked and Pending rows expose a concise reason,
owner, and safe next-step link where one is available.
Critical-priority blocking is also implemented per the approved rule: an
active Critical finding in Needs action blocks only Medium, Low, and
Informational findings sharing its canonical subject or participant; High,
Paused, Pending, resolved, and already Blocked Critical findings do not block.
Generic absent-result recovery no longer manufactures positive evidence;
clearing remains dependent on producer-specific current recovery authority.
Rendered labels are authoritative for selected-group sorting. The database
Evidence and Context projections now cover the complete operator-visible text,
including servicing, identity, Hudu, platform, software, and offline paths.
The Identity subject projection uses the renderer's canonical-hostname
selection. Database filters, HTML ordering/pagination, and CSV use that shared
selected-scope ordering contract. PostgreSQL execution plans and cardinality
remain to be measured against the deployed data.

The Critical-priority projection is also enforced at operator Hudu action
queueing, notification candidate selection, and notification send-time
rechecks. Participant coverage and administrator coverage compare exact
participant identity sets, excluding context participants.

Validation: the focused Issues queue suite passes (37 tests); the full
Operations suite passes (172 tests, 2 opt-in PostgreSQL tests skipped); Django
checks, migration-drift checks, Python compilation, targeted Ruff checks, and
`git diff --check` pass.
`httpx==0.27.2` is now installed locally and the full ingest suite passes
(246 passed, 57 skipped). The hardcoded-domain ratchet now documents the
operator vocabulary and pre-existing dispatch definitions; the software
read-model test now stubs the catalog projection introduced by its current
implementation. The latest Pending terminology, conservative visibility, and
Critical-priority corrections add focused queue coverage, and the Operations
suite remains at 172 passed with two PostgreSQL tests skipped.

Deployment verification on 2026-09-22: commit `d0ea05f` was pushed to both
remotes; the Operations `/healthz` endpoint returned HTTP 200; the Operations,
ingest, Postgres, and Metabase containers reported healthy; and all Django
migrations reported applied. The first shell query incorrectly returned zero
tenant rows because it omitted the required `operations.tenant_id` session
context. A corrected read-only query under tenant 1 found 24,548 open and
445,919 resolved Findings, 6,491 current-taxonomy assessments, successful
recent source/evaluator runs, and 4,229 complete observation snapshots.

Production reconciliation classified all 22,749 governed open Findings
exactly once: 2,213 Needs action, 184 Blocked, and 20,352 Pending; 1,799
Software decisions remain separate. It also exposed an O(n²) Critical-priority
scan in the shared operator-state projection. The current local follow-up
indexes rows by ID, reuses the selected projection for unfiltered fleet cards,
and adds regression coverage. The first authenticated HTML smoke test also
found a missing outer `{% endif %}` in `findings_queue.html`; the first CSV
smoke test found unescaped `%` literals in a psycopg RawSQL expression. Both
are corrected locally and covered by focused tests.

Commit `82674f5` pushed the performance, template, and percent-literal
corrections. Its authenticated smoke run found one additional RawSQL issue:
PostgreSQL gives `||` higher precedence than `->>`, so every JSON-text
extraction used as a concatenation operand must be parenthesized. The current
local follow-up makes that correction across the Evidence projection and adds
a regression test. Validation: 41 focused Issues tests pass; Django checks,
migration-drift checks, Python compilation, targeted Ruff, and `git diff
--check` pass. No migration or production data mutation is required.

Commit `ccfe5b5` pushed the RawSQL precedence correction to both remotes.
After the automatic update, an authenticated read-only production HTML request
returned HTTP 200 in 21.83 seconds. A scoped authenticated CSV export returned
HTTP 200 in 16.414 seconds with the expected operator-facing columns and no
engine-internal columns. A full-fleet CSV export did not complete within four
minutes and was interrupted without any data mutation. This proves the page,
template, and scoped CSV are correct, but full-export performance remains a
separate follow-up.

Local full-export optimization is complete: database annotations are now added
only for requested column filters, rather than selecting every expensive
rendered expression for every exported row, and `format=csv` returns before
page-only affected-device summaries and collapsed-group aggregation. Sorting,
column-filter, and CSV label contracts remain unchanged. Focused validation is
41 tests passing with Django checks, migration-drift checks, compilation,
targeted Ruff, and `git diff --check` passing.

Commit `7c3dd75` pushed the full-fleet CSV optimization to both remotes. The
authenticated read-only production export completed successfully in 40.188
seconds for 22,749 rows, with the expected operator-facing headers and no
engine-internal columns. This replaces the prior export that did not complete
within four minutes. The default authenticated HTML request remains successful
at 21.83 seconds. No migration or production data mutation was required.

The full CSV export is now within an acceptable interactive-export window, but
the default Issues page still spends 21.83 seconds evaluating every retained
finding state solely to populate fleet cards and collapsed Type headers. The
next scope is to replace that full per-finding projection on the unopened
default page with aggregate state counts, while retaining exact per-finding
Critical-priority evaluation for opened groups, filtering, and exports. No
migration is in scope.

The current local performance correction preserves the exact state model more
directly: a Finding with no current non-context assessment is necessarily
Pending, so the participant-completeness query now runs only for current
assessment candidates. Production has 4,807 such candidates among 24,549
active Findings; 19,742 are direct Pending rows. Focused validation passes
(41 tests, Django checks, migration-drift checks, compilation, targeted Ruff,
and `git diff --check`). Next action: commit/push this correction and measure
the default authenticated Issues-page latency on production.

Follow-up local fixes: Categories are collapsed by default and reopen for the
selected drilldown; filtered database pages now replace their raw Finding
objects with the enriched display rows before template rendering. The latter
fixes the reproduced `NoReverseMatch` 500 from Type and column-filter requests
whose action controls received an empty Finding ID. The default collapsed queue
also no longer expands the complete Finding population through the expensive
software-exposure view merely to calculate a rollup it does not display; opened
Types and the explicit device CSV retain the full affected-Computer rollup.
Next action: validate the complete correction, commit/push it, and rerun the
authenticated production timing plus Type and column-filter smoke tests.

Focused validation now passes: 44 Issues queue tests, Django checks,
migration-drift checks, targeted Ruff, Python compilation, and `git diff
--check`. The Type navigation header is explicitly kept on one line. No
migration or production data mutation is in scope. Next action: commit/push
the corrected default queue, then run the authenticated production smoke tests.
The Work status column now uses one human-facing state (Needs action, Blocked,
Pending, Paused, or the lifecycle fallback) rather than a generic status plus
a redundant explanation. A note remains only when it adds information, and the
CSV uses the same Work status/Note contract. Expanded Type state links are
stacked on separate lines for scanning. Each Type header and its expanded state
links are one grid item, preventing an expanded list from taking a neighboring
Type's grid cell; the header keeps only shown/unresolved totals because the
expanded list carries state totals. Next action: validate this display
correction together with the queue performance changes before commit.
Filtered active queues now reuse the one exact fleet-state projection for the
unfiltered summary cards; previously they recalculated the complete state model
for both the selected Type and the fleet. Resolved-history scopes still receive
their own projection because they are not a subset of the active fleet. Next
action: validate the consolidated queue correction locally and in production.
The affected-Computer rollup now runs only for the explicit device CSV. It is
not needed to render the normal Issues table and previously added 6.4 seconds
to selected-Type browsing through the fleet-wide software-exposure view. Next
action: validate filtered identity review latency and the former column-filter
500.
For a selected single-condition Type or individual Issue, the default Group
sort now uses the stable ID tie-breaker directly because every displayed Group
and Issue label is equal; it avoids evaluating the expensive rendered-issue
SQL merely to compare identical labels. Next action: validate that Type
drilldown and the evidence column filter in production.
Production verification complete on 2026-09-22: the default queue returned
HTTP 200 in 13.879 seconds; the identity-review Type returned HTTP 200 in
16.358 seconds; and the same Type with the Evidence column filter returned
HTTP 200 in 11.378 seconds. The latter two requests previously exceeded the
30-second probe window, and the filtered-page `NoReverseMatch` 500 no longer
occurs. The running Operations container is healthy and includes commit
`1ac4033`. Local validation for the final corrections: 48 focused Issues tests,
Django checks, migration-drift checks, targeted Ruff, compilation, and diff
checks all pass. The plan checkpoint is complete; this record remains local to
avoid a documentation-only deploy commit.
Pause only for a material product decision, conflicting user work, migration
approval, production mutation, or separate commit/push authorization.

Status-message clarity correction in progress. Scope: the Issues work-status
cell and Patching policy-state labels. Decision: Pending means no operator can
act until current information arrives; it must not name “Automatic
reevaluation” as an owner. Status cells will show a short plain-language note
and, only where useful, one clear next action. Patching will define In scope,
Excluded, and Not managed where operators see their counts. Validation: focused
queue/patching tests, Django checks, and template rendering checks. Next action:
update the centralized guidance and patching copy.

Implemented locally: Pending now states “Waiting for current information” and
“Checked automatically when information updates,” with no fictitious automatic
owner. Source, patch, and reporting routes name the responsible team and use
short “Check …” actions. Patching scope tiles and their help text now define
In scope (patching expected), Excluded (do not patch), and Not managed (no
patch service). Next action: run focused validation and inspect every rendered
status-message branch.

Patching workflow clarity correction implemented locally. The five work items
are now labeled by operator outcome: No patch installed yet, No recent patch
activity, Restart required, Update repeatedly failing, and Approved updates
not installed. Each Patching card includes a short next action; the last is
explicitly marked client-level. Detail text and dashboard/client summaries use
the same vocabulary. Next action: add focused label/rendering coverage and
validate.

Manual Computer retirement in progress. Scope: make the existing audited
retirement operation visibly available from every non-retired Computer's
Source records section to users with `operations.manage_lifecycle`; do not
require a lifecycle finding or `pending_cleanup` status. Keep the required
reason, confirmation, permission boundary, tenant scoping, evidence retention,
and existing restore path. No migration, source mutation, or automatic
lifecycle-policy change is in scope. Implemented locally: the Source records
section now shows a Manual retirement control for every non-retired Computer
to authorized operators; the existing post action remains the enforcement and
audit boundary. `git diff --check` passes. Container-based validation is not
available because the local Compose stack is stopped. Workstation Django checks
cannot run under its Python 3.14 environment because `shared` is absent from
its import path; the template-only Ruff invocation is inapplicable. Next
action: validate with the supported Operations environment, then obtain
separate commit and push approval.

Issue workflow correction in progress. Scope: every operator-visible Issue
gets a direct, one-click investigation destination from its queue row. Use
the existing Computer, client, software, patch evidence, source health, merge,
and Hudu surfaces where they are authoritative; provide a consistent
operator-facing finding review fallback where a specialized surface does not
exist. Keep the current row controls and bulk acknowledge, resolve, snooze,
retire, and Hudu archive actions. Do not expose engine internals, weaken
permissions, or add a schema migration. Implemented locally: every row now
has a direct Review action. The review page uses the safe existing evidence
summary and gives direct destinations for Computer/source records, client,
software, client-scoped patch evidence, Hudu records, duplicate Computers, or
source health; a source-health fallback keeps platform-level Issues reviewable.
The existing per-row and bulk actions remain available. Validation: focused
Issues tests pass (52), Django checks pass, all three changed templates load,
Python compilation passes, and `git diff --check` passes. Next action: obtain
separate commit and push approval; no migration or deployment action is in
scope.

Release preparation complete: VERSION and CHANGELOG are `0.126.2`; no migration
is included. The validated workflow, status-copy, patching, and manual
retirement changes are one operator-workflow release. Next action: commit and
push the approved release without a manual redeploy.

Issue action simplification in progress. Goal: make the Issues queue a review
surface rather than an alert console. Scope: rename the column to Status; keep
only its short state and one useful explanatory line; remove acknowledgement
and manual resolution from row and bulk controls; replace the More expander
with consistent direct Review, Pause, Exclude, and applicable specialized
actions; and render historic acknowledged findings as Open in the operator
queue without changing their audit history. Refresh is deliberately out of
scope until an authenticated, safe, issue-scoped collection operation exists:
the current ingest endpoints either start a whole source or require an
ingest-specific scope selector. Exclude remains an explicit operator override
and must retain a reason. No migration, source mutation, or deployment is in
scope. The operator requires Refresh, so add an authenticated Operations
endpoint that queues the existing Ninja software demand run for exactly the
finding's linked Computer; do not make a broad source run look scoped. Show it
only where a current Ninja device link exists. Validation: focused queue tests,
Django checks, template rendering, compilation, and diff check. Next action:
implement the queue, action, and scoped refresh contract locally.

Implemented locally: Status replaces Work status and contains only the state,
one useful detail, and a pause date. Acknowledged persisted findings render as
Open in Issues while their audit history remains unchanged. Row and bulk
controls now use one compact control style with no More expander; review,
Pause, Exclude (reason required), Keep separate, Hudu archive, and Refresh are
direct actions. Refresh is an authenticated Operations endpoint that resolves
only a current Ninja-linked Computer and queues the existing `id=<ninja-id>`
software demand run; it is unavailable for every other Issue, rather than
claiming to refresh information it cannot collect. The dedicated Review page
is investigation-only and no longer reintroduces acknowledgement or manual
resolution. Validation passed: 53
focused Issues tests, Django checks, both changed templates loaded, Python
compilation, scoped import lint, and diff check. The full Ruff run remains
blocked by 65 pre-existing violations in `apps/core/views.py`. Next action:
release the approved `0.126.3` operator-workflow change; no migration is
included.

Targeted refresh and action-density correction in progress. Scope: give every
Pending Issue the narrowest truthful Refresh action available (Computer data,
specific source data, or reevaluation only when it can act on current
evidence), keep its result explicit, reduce row controls to the table's visual
scale, and keep Subject links pointed at the authoritative Computer, client,
software, or source review surface. Do not present a fleet-wide collection as
a Computer refresh or change source-derived state from Operations. No schema
change or production action is in scope. Validation: focused queue tests,
Django checks, template rendering, compilation, and diff check. Next action:
map Pending subjects and existing collector/evaluator endpoints to safe
targets.

Implemented locally: Pending rows now expose Refresh through one shared
dispatch path. It selects the narrowest available operation: current
Ninja-linked Computer software data, the registered source named by the
finding's evidence, or platform reevaluation when only already-collected
evidence can be checked. Source-bound Subjects now link directly to Source
health. The Actions column uses a compact fixed-width, single-line control
set sized to the table row. Jobs now links to Targeted refresh, where an
operator can search and select a Computer, choose a source, or request an
explicit reevaluation; it calls the same functions as the Issue action. No
schema change or production action was performed. Validation: focused queue
tests, Django checks, template loading, compilation, and diff check pass.
Next action: review the local behavior and obtain separate commit/push
authorization.

Main-table information-density correction complete locally. Finding remains the
issue and Subject remains its affected object; condition-specific evidence and
source/lifecycle timestamps are merged into Context, with no separate Evidence
or Evidence date columns or controls. CSV and visible table filtering/sorting
use the same merged Context contract. No schema, source, or production change
is in scope. Validation: 55 focused queue tests, Django checks, template
loading, compilation, import-order lint, and diff check pass. Next action:
obtain separate commit and push authorization if the local change is approved.

Fleet-summary card refinement complete locally. The unfiltered Issues summary
now reuses the shared compact tile pattern: blue for neutral totals and
software decisions, red for Needs action, amber for Blocked, yellow for
Pending, and gray for Paused. Counts and destinations are unchanged. No
schema, query, source, or production change is in scope. Validation: 55
focused queue tests, Django checks, template loading, and diff check pass.
Next action: obtain separate commit and push authorization if the local change
is approved.
