# Issues queue operator model and coverage correction

## Status

**Implementation complete locally; deployment verification pending.** This supersedes the
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

Next action: after an explicitly authorized deployment, run the deployed
PostgreSQL query-plan and row-count review, followed by read-only production
reconciliation of card conservation, Category/Type totals, assessments,
links/CSVs, and service health.
No commit, push, deployment, migration, or production data mutation has been
performed for this plan yet.

No commit, push, deployment, migration, or production data mutation has been
performed for this plan yet.
Pause only for a material product decision, conflicting user work, migration
approval, production mutation, or separate commit/push authorization.
