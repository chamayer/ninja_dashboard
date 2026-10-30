# PLAN-003 — Issues queue requirements reconciliation

Current contract: [PLAN-003 current design](PLAN-003-current-design.md).
This checklist retains historical requirements and the first review's choices;
later amendments are consolidated there. In particular, older Readiness controls,
general row expansion and software-filter alternatives below are not the current
implementation contract. The review report retains detailed verification evidence.

## Status and scope

Active — design phase, reopened by the user on 2026-10-26. This is the
requirements checklist for the corrective proposal, not approval to implement
the Issues page. Commit, migrations, deployment, and production actions retain
their separate approval boundaries.

Local baseline inspected: HEAD `0c830ff` and the existing dirty worktree.
Observations below are from code and committed history. The subsequent
[findings review and proposal](PLAN-003-review-proposal.md) adds an aggregate,
read-only production snapshot and the full 71-type review. Neither document
claims rendered-page acceptance. Existing unrelated changes are preserved.
Historical document status lines are not current plan status; the plan registry
and Operations BLUEPRINT own that status.

## Approved scope amendment — consolidated findings and relationships

User instruction, 2026-10-27: add consolidation of entity and admin findings to
PLAN-003. The target design is one authoritative findings store, with one
relationship mechanism for coverage and prerequisites. This supersedes the
historical requirement to retain separate `findings` and `admin_findings`
storage. It approves planning and design scope; it does not authorize executing
a migration, retiring tables, changing production data, or implementing the
page before the complete proposal is reviewed.

- Preserve distinct Computer, client, software, source and platform subjects,
  type-specific evidence/lifecycle rules, and permission-gated actions within
  the common model. An admin classification may remain useful metadata; it
  must not require a second active finding ledger or query pipeline.
- Consolidate covered and prerequisite handling into the same relationship
  contract across all finding subjects. A covering relationship can nest a
  symptom; a prerequisite relationship preserves an independent issue with a
  specific prerequisite link. Both use consistent identity, scope, counts,
  history, related-item rendering and change propagation.
- Keep the existing execution/evidence safety checks. An engine execution gate
  does not by itself mean a human cannot review an issue. The proposed removal
  of the separate operator Blocked bucket must be reconciled with the remaining
  Readiness labels; unifying storage does not itself settle that presentation.
- Current Computer cover uses type rules plus derived parent IDs; Admin/Jobs
  handling separately closes some dependency findings with upstream references.
  The target design must replace this split with one defined behavior. Preserve
  historical closures and reasons; do not reopen or erase them simply to migrate.
- Candidate lifecycle storage is not part of this merger. Pending identity
  decisions still participate in the queue through the agreed read contract;
  do not manufacture canonical findings or identities for observed-only evidence.
  PLAN-004 identity and PLAN-021 candidate-lifecycle repair stay outside scope.

Required technical design before implementation approval:

1. Audit both ledgers' producers, queries, state writers/triggers, participants,
   assessments, history/versioning, notifications, source actions, exports,
   review handlers, foreign keys, raw SQL and all `row_kind` references. Identify
   each consumer's replacement and its compatibility requirements.
2. Specify the common finding fields, subjects/client scope, episode/condition
   uniqueness, state authority, and relationship rules. Use confirmed scope
   evidence for relationships; reject self-links, cycles and cross-tenant links
   through the controlled writer and appropriate database enforcement.
3. Define a deterministic mapping from legacy `(row_kind, id)` to the unified
   finding identity. Preserve existing IDs where possible; detect collisions
   and active cross-ledger duplicates without silently discarding history or
   equating unrelated conditions. Retain resolvable legacy references.
4. Plan the schema expansion, data conversion, producer/reader cutover,
   compatibility period, rollback boundaries and eventual retirement of the
   second active ledger. Use new reviewed migrations; preserve old migrations
   as history. Any compatibility projections must not remain independent writers.
5. Verify tenant RLS, read/write privileges, action permissions, history,
   assessment freshness, pauses, severity, covered/prerequisite changes and
   all queue count/filter/paging/export behavior across the cutover. Compare
   full populations, not only row counts; explain every identity/status change.
6. Present affected files, exact migrations, data effects, rollback plan and
   validation evidence. Record the accepted durable architecture in a decision
   record before implementation closeout. Migration execution, commit and
   deployment retain their separate authorization boundaries.

## Evidence sources

- **P1:** [Original taxonomy and count-contract design](https://github.com/chamayer/ninja_dashboard/blob/e5a8f51/operations/.work/plan.md).
- **P2:** [Operator model and page design](https://github.com/chamayer/ninja_dashboard/blob/d0ea05f/operations/.work/plan.md), especially WP5-WP8.
- **C:** [Central work queue design](../../../.work/central-work-queue-design.md).
  Its header still says draft; its agreed principles and implementation history
  are corroborated by the [archived checkpoint](../../../docs/archive/workspace-cleanup-2026-10-20/plan.md)
  and the commits below. Do not treat every proposed work item as approved.
- **R:** [Finding types registry specification](../../../.work/finding-types-registry-spec.md),
  implemented by `e7de3fb`; current reader: [finding_registry.py](../../apps/core/finding_registry.py).
- **S:** [Finding state design](../../../.work/finding-state-design.md), including
  its live-cover amendment; [ADR-0031](../decisions/0031-finding-state-is-stored-and-written-in-the-same-transaction.md).
- **A22/A23:** [Taxonomy ADR](../decisions/0022-policy-defined-issue-taxonomy.md)
  and [operator state/count ADR](../decisions/0023-issues-operator-state-and-count-contract.md).
  These contain superseded provisions identified below.
- **L:** Later committed changes: `2767c8a` severity summaries;
  `d0ea05f` state drilldowns; `943d718` concise work status;
  `041ae1c` and `e5afd28` category-first navigation;
  `5e98e02` review/pause/exclude actions; `f95c589` merged Context column;
  `14135f5` admin findings; `141ad94` pending identity matches;
  `eff0ed9` and `853fac0` software decisions in Issues;
  `b2c646a` client-page mapping decisions; `31942a5` common finding view;
  `629d739` server-table controls.

Current paths reviewed: [queue view](../../apps/core/views.py),
[template](../../templates/findings_queue.html),
[queue tests](../../apps/core/tests/test_findings_queue.py),
[mapping tests](../../apps/core/tests/test_client_mapping_workflow.py),
[common projection](../../apps/core/migrations/0352_issue_findings_read_model.py),
and [operator state mapping](../../apps/core/conditions/operator.py).

## Requirements checklist

"Present" means visible in current code, not newly validated behavior.
"Partial" means at least one item kind or query path differs.
Treatment describes what the corrective proposal must account for.

| ID | Requirement and source / amendment | Current code | Treatment in proposal |
| --- | --- | --- | --- |
| Q01 | One Issues inbox for waiting work, including admin findings. C; `14135f5`, `31942a5`; storage separation superseded by the 2026-10-27 scope amendment above. | Partial: common taxonomy/counts, separate authoritative ledgers, result tables and query paths. | Design one authoritative findings store and one shared queue contract, with an explicit identity/history-safe migration. |
| Q02 | Pending identity decisions belong in Issues; observed-only evidence does not become artificial findings. `141ad94`. | Pending candidates are counted and displayed separately, capped at 200. | Include eligible candidate work in the same scoped result contract; preserve its identity and review workflow. |
| Q03 | Overview counts link to Issues; overview pages do not become parallel work queues. C; `6189f37`. | Home alert counts six mapping types across entity/admin stores, opens all Inventory, and does not filter its count to critical severity. | Make label, count, and destination describe exactly the same population; do not narrow to name conflicts alone. |
| Q04 | Permissions gate actions; queue visibility is not split into admin and non-admin work. C. | Issues is login-protected; technical/action destinations have their own permission checks. | Preserve visibility and enforce existing action permissions server-side. |
| G01 | Keep the five category names; derive category/type membership, labels, and order from one registry. C; R supersedes policy taxonomy in A22. | Present through `finding_registry.build_taxonomy()`. Historical type/group totals have changed. | Use current registry data; do not freeze an old count of types or invent another classification map. |
| G02 | Expose every nonempty Type under its Category before finding pagination; retain empty Types in filter options. P2 WP6. | Category/type navigation is aggregated before pagination, but populations differ across item kinds. | Preserve complete group discovery and reconcile group populations. |
| G03 | General queue starts collapsed; selected Category, Type, Issue, or Computer/evidence drilldown opens its relevant scope. P2; `397b33a`. | Present for main finding/navigation paths. | Preserve automatic expansion; a deep link must reveal its target rows. |
| G04 | Opening a Category displays its rows immediately; Type is an optional refinement. Show Type rows only when useful; avoid redundant single-state choices. `041ae1c`, `e5afd28`. | Present, but all category navigation remains vertically ahead of results. | Keep category-first behavior and reduce distance to the selected results. Sidebar placement remains a proposal, not a historical requirement. |
| G05 | Type headers have counted Needs action / Blocked / Pending drilldowns. P2; `d0ea05f`, `943d718`. | Present as Review by state; admin additions do not have equivalent state counts. | Preserve drilldowns and define a valid state contract for every participating item kind. |
| G06 | Severity breakdowns/count links existed on category cards and Type headers. P1; `2767c8a`; later P2 replaced severity dashboards with state summaries. | Severity filter remains; earlier breakdowns are absent. | Record the chronology; whether to restore severity subgrouping alongside state drilldowns needs an explicit design decision. No arbitrary Group by switch was found. |
| G07 | Critical work sorts first; low/info sorts last and collapses within its Category. C; S removes critical-priority blocking as a state. | Gap: default main sort is group/issue labels or ID; admin rows use detection time; no low/info grouping collapse. | Carry this requirement into ordering/expansion design and reconcile the software ordering exception. Do not change finding eligibility to simulate priority. |
| N01 | Fleet summary is explicitly global and independent of scoped filters. P2/A23; Covered adds a seventh shortcut in S. | Seven cards exist; main state totals come from entity finding state, while admin/candidate counts are added elsewhere. | Preserve global-versus-filtered distinction; specify inclusion and conservation across all queue item kinds. |
| N02 | Group headers reflect full scoped matches and useful unresolved baselines, not just the current page. P2/A23. | Partial: current counts add admin/candidates, unresolved/state counts follow different paths. | Use explicit shared populations and label current matches versus unresolved context accurately. |
| N03 | Count issue rows separately from affected Computers/clients; software exposure must not multiply issue totals or duplicate affected Computers. P1; later performance work limits affected-Computer expansion to explicit CSV. | Device CSV uses exposure; result summary and Issues CSV cover regular findings before admin/candidate assembly. | Preserve natural item grain, deduplicated affected-Computer export, and exact scope reconciliation. |
| N04 | Status, Attention, and Severity stay independent; missing/stale assessments remain visible as Pending, not actionable. P2/A23; S. | Present for main finding state; admin/candidate state mapping remains separate or absent. | Reuse valid existing state authorities; specify missing semantics rather than assigning invented actionability. |
| N05 | Retained/offline and resolved evidence remains discoverable through appropriate review filters. P1/P2. | Main findings retain offline evidence; Resolved filter exists. `status=all` now normalizes to active. | Preserve historical review access and current operator meaning; do not assume the historical all-status URL still means every status. |
| F01 | Category → Type → Issue controls depend on each other, default to All, and preserve unrelated filters. P1/P2; later category-first navigation. | Cascading controls and URL copying exist; Issue without a valid selected Type is cleared. | Retain dependency rules and produce valid direct links; changing scope must not silently erase unrelated selections. |
| F02 | Support Attention and secondary Status, Severity, Client, Platform, online, search, confidence, OS and Computer-type scopes where meaningful. P1/P2; current controls. | Partial: regular findings have broad filters; admin rows mainly apply type/status/severity; candidates mainly pending/client. | Define applicability for each kind. An irrelevant device filter must not silently leave unrelated rows visible. |
| F03 | Column filters and sorting operate on displayed values over the full selected dataset before pagination. P2 WP7; `f95c589`, `629d739`. | Present for regular findings' five current columns; separate admin/candidate tables have different behavior. | Apply equivalent scoped behavior throughout the queue; keep merged Context semantics. |
| F04 | Clear column filters removes all table parameters while preserving scope. P2 WP7. | View builds `table_clear_query`; current template does not expose a Clear column filters link. | Restore an explicit scoped Clear control. Reset-all must remain distinguishable. |
| F05 | Group counts, result total, sorting, pagination, HTML, and CSV share a query contract. P2 WP7. | Gap: normal rows page at 50; other tables cap at 200; main count/CSV are calculated before those tables. | Reconcile all result paths before changing visual layout. No silent truncation or omitted row kinds in Issues CSV. |
| F06 | Computer drilldowns include inherited software exposure; evidence-group keys are registry-controlled; malformed device/evidence scopes fail closed. P1/P2; current drilldown tests. | Present in main finding scope; other item kinds do not share it. | Preserve exact drilldown meaning and validate equivalent scope handling where applicable. |
| U01 | Compact page with title/exports, global summary, scoped controls/summary, hierarchical grouped results; remove repeated headings, navigation and competing counts. P2 WP5/WP6. | Panels, navigation, and three result paths stack vertically. | Consolidate hierarchy while preserving grouping, counted drilldowns and current scope visibility. |
| U02 | Human-readable registry names; meaningful subject/entity links; short useful reasons; engine internals stay in diagnostics. P1/P2; R; `943d718`. | Main rows use these labels; specialized tables have distinct columns and explanations. | Keep one consistent operator vocabulary and row presentation while retaining useful evidence. |
| U03 | One concise work-status label; avoid repeated reasons and fabricated Owner/Next step columns. `943d718`; later operator mapping. | Main rows comply; admin table shows stored status. Acknowledged is now shown as Open in operator mapping. | Preserve later simplification; do not restore obsolete Acknowledged UI or removed columns from older designs. |
| A01 | Every row has a review path to relevant evidence/decision; client mappings are decided on the client's page with return scope preserved. `5e98e02`, `b2c646a`. | Main Review route, admin resolution links and candidate review links differ. | Normalize queue entry without replacing domain-specific decision/evidence destinations. |
| A02 | Retain permitted bulk actions, Pause and reasoned Exclude overrides; remove generic Ack/Resolve actions. `5e98e02`; C W3. | Main finding controls and action registry implement these; bulk endpoints accept Finding IDs. | Preserve authorization, reasons, and history; define eligible selections without feeding other item kinds into Finding-only handlers. |
| A03 | Pending work can refresh relevant current information; non-software refresh must not trigger software refresh. `bca7230`; current focused tests. | Main pending rows expose targeted refresh. | Preserve bounded refresh routing and availability rules. |
| A04 | Software approval and capability decisions are queue actions; undecided software is included and resolved through decisions rather than Pause/Exclude. C W3; `eff0ed9`, `853fac0`. | Present. Software decision groups have an explicit most-widespread-first ordering. | Preserve later inclusion/action rules; reconcile this ordering exception with general urgency ordering. |
| D01 | Covered dependents remain findings with history, evaluation, explanation, parent link and reveal; they return when cover clears. C; S live-cover amendment. | Main entity paths hide Covered by default, provide a Covered filter/card and parent counts/reveal. | Preserve live-cover authority and exact scope. Read it; do not recompute suppression in presentation code. |
| D02 | Severity inversion under a parent must be visible; critical presence is a badge, not a reason to block unrelated work. C safeguards; S. | Main rows show covered counts, higher covered severity note and critical-subject link. Other result paths differ. | Retain these signals and state semantics in common row presentation; verify scope and chain behavior. |
| D03 | Page changes must not alter producer predicates, finding severity, canonical identity, alert eligibility, or history. P1/P2; C; S. | These have their own producers, registries and action handlers. | Preserve boundaries. Candidate lifecycle repair stays with PLAN-021; identity repair stays with PLAN-004. |
| P01 | Landing uses grouped database counts; selected scope loads one bounded page and batches detail reads. P2 WP7; `cc4251f`, `2dc9748`; S. | Main path is bounded; auxiliary paths have independent caps and queries. | Keep bounded server queries; do not merge already-truncated Python lists and call that global pagination. |
| V01 | Behavior tests must prove count conservation, >500-row group visibility, filtering, sorting, Clear, permissions, HTML/CSV consistency, and performance. P1/P2; S. | Many tests assert source strings; some action/state behavior tests exist. No tests or rendered-browser checks were run for this discovery. | Require representative PostgreSQL/request/browser acceptance evidence, including mixed kinds, direct links, and large groups. |

## User decisions — 2026-10-26 design review

- Three view modes: Flat list; Category → Type; Category → Type with
  subgroups. Subgroups can be Severity or Readiness. "Readiness" is the
  operator label for the existing Attention concept; its plain labels are
  Ready to act, Blocked, and Waiting for information. This does not authorize
  changes to stored state semantics; Paused, Covered and Resolved applicability
  still needs explicit treatment.
- Default: Category → Type with Severity subgroups, ordered Critical, High,
  Medium, Low, Info. Remember the operator's view/grouping choice.
- Rows retain both severity and readiness regardless of grouping. Switching
  views preserves the filter population and consistent counts.
- Sorting preserves Category/Type/subgroup boundaries and applies to the full
  matching dataset before pagination. Flat-list sorting is global. Row sorting
  may use client/subject, issue, readiness, or date. Default row order is
  Ready to act first, then most recently detected, with a stable item-identity
  tie-breaker.
- Software approval requests keep a specific row-order exception: within the
  selected Severity/Readiness grouping, most affected Computers first, then
  latest detection, then stable item identity. Show Affected Computers as a
  sortable column so this order is understandable. Software incidents such as
  vulnerabilities or malicious software use the normal readiness/date default.
- Direct links open the appropriate category, Type and subgroup. On ordinary
  entry, automatically open one populated path to the highest-priority matching
  work. Rank Severity (Critical → High → Medium → Low → Info), then Readiness
  (Ready to act → Blocked → Waiting for information); break category/Type ties
  using configured registry order. With no Critical matches, use the next
  severity present. Group size alone does not raise priority. This supersedes
  the old entirely collapsed landing design. Cross-kind state/action semantics
  still need review; this is not implementation approval.
- Group and subgroup counts stay visible and represent the full filtered set.
  Expanding a group/subgroup loads 50 rows with its own page controls; paging
  changes only that result list. Flat list has one normal set of page controls.
- One sibling can be open at each hierarchy level. Opening another sibling
  collapses the prior one; reopening restores its page and sort position.
  There is no Allow multiple groups open setting.
- Every Category and Type has a total and compact severity/readiness breakdowns.
  A Severity subgroup shows readiness counts; a Readiness subgroup shows severity
  counts. Breakdowns describe the full filtered scope before pagination; counts
  are drilldown links. Different dimension breakdowns describe the same items
  and must not be added together. Keep summaries compact rather than creating
  additional dashboard panels.
- Paused issues are excluded from the default open-work rows until the pause
  expires; unresolved items return when the pause expires. Global Unresolved
  still includes paused work; filtered row counts describe only included items.
- Paused links exist in the page summary (fleet scope) and Category/Type headers
  (that scope). Example: `Client mapping — Open (18) · Paused (3)`. A scoped
  link retains relevant client/search filters; a global link opens the global
  population its count describes. The Status filter handles narrower scopes;
  do not repeat Paused links on every Severity/Readiness subgroup.
- Use `Label (count)` consistently across summaries, categories, Types and
  subgroups. Use Open rather than Active in operator status controls/counts so
  the labels agree. Open and Paused counts are equally clickable and have the
  same surrounding scope; each describes its own included population.
- Covered child issues stay out of default rows and are accessible beneath
  their parent through `Related issues (6) — covered by this issue`. The link
  expands the retained children in place, showing why each is covered. They
  remain unresolved with their own history and return to normal visibility
  when cover clears if still unresolved. Use the existing live-cover authority.
  The proposed "Explained issues" wording was rejected as suggesting resolution.
- Common row columns: Severity, Issue, Client / Subject, Readiness, Context,
  Actions. Flat list adds Category → Type under the issue name; grouped views
  avoid repeating those headings. Client and subject use separate linked lines
  where applicable. Readiness has a short useful blocker/waiting reason. Context
  contains concise evidence and last-detected date. Review is primary; other
  controls require applicability and permission. Later user-approved amendment:
  no general row expansion; Review opens evidence, history, mapping comparisons
  and related context in the owning review workspace. The specific Related
  issues expansion for covers/requires remains. Software approval requests
  additionally show the sortable Affected Computers column. Visual details will
  be reviewed after implementation; implementation remains subject to the
  current design gate.
- Clarification (2026-10-27): default rows are all open, unpaused work within
  the selected scope, with the existing covered-child behavior. The intervening
  suggestions for Ready-to-act-only default views, a work-view tab row and a
  combined Show dropdown were not adopted. Keep the accepted filter set and
  grouping modes; operators do not have to choose a work view before starting.
- Readiness never changes severity. Severity expresses seriousness; Readiness
  expresses whether the next supported action can be taken now. Do not rename
  Readiness to Priority or add a separate Priority field. Default priority
  ordering uses severity first and readiness within severity; within a Severity
  subgroup this is the agreed readiness/date ordering. Preserve the approved
  software-approval impact-order exception. Explicit row sorts still work.
- Unmatched work stays in its normal Category/Type in the same queue. Show
  Unassigned client alongside the reported name and platform; include Unassigned
  in the Client filter. Review opens the matching decision surface. Do not imply
  a confirmed client or Computer identity before it is established.

## Superseded provisions and unresolved decisions

1. Policy-owned taxonomy and fixed historical type totals are superseded by R.
   The five category names stay; current registry membership and order prevail.
   The registry change explicitly removed old category tables and URL shims;
   restoring every legacy alias is not a current requirement.
2. P2/A23 excluded software policy decisions and specified six summary cards.
   Later C/W3 and committed software work included decision prompts; Covered
   added another state/card. Do not use the old exclusion or six-card formula
   as acceptance criteria. Define the current count populations explicitly.
3. Earlier Acknowledged operator controls, Owner/Next step fields, and separate
   Evidence/date columns were simplified later. Preserve Open/Paused/Resolved
   handling, concise work status, and the merged Context column.
4. Severity summaries and later state drilldowns are both historical facts.
   A configurable severity/state subgroup selector is not substantiated by the
   reviewed historical record. The user has now approved optional Severity or
   Readiness subgroups and the view modes recorded above.
5. C calls for low/info collapse and urgency order; S retains critical-first
   priority, while software decisions have a later spread-based order. Specify
   defaults, exceptions, explicit column-sort behavior and direct-link expansion
   before implementing. The user has now settled the normal subgroup/row sort
   above; ordinary entry now opens one highest-priority path and direct links
   open their target. Other sibling groups stay collapsed. The software ordering
   exception is now approved as recorded above.
6. C permits separate authoritative storage, and S explicitly described three
   small side tables. Therefore separate tables are not by themselves proof of
   violating every historical design. The demonstrable gaps are inconsistent
   scope/count/export/pagination behavior and excessive distance to selected
   work. The user has since expanded PLAN-003 to design one authoritative
   findings store; this supersedes the old storage-separation constraint.
7. Admin subjects/clients are lost in the current common view; pending generic
   candidates are outside it. A normalized read contract needs an explicit field,
   state, filter, export and action-applicability design. A projection migration
   may be needed; an assurance of "no schema change" is premature.
8. PLAN-003's former completed status described delivered W7-W9 implementation.
   It did not establish that the complete page contract passed browser and
   cross-kind acceptance. The plan is reopened for design, retaining prior work.

## Accepted filters and resolution links — 2026-10-27

Accepted by the user on 2026-10-27. This approves the design choices below;
application implementation remains subject to the current design gate.

- Global operator filters: Client, Severity, Status (Open/Paused/Resolved),
  Readiness and Search. Category/Type/Issue selection remains available through
  group navigation and equivalent selectors in Flat list. Keep column filters
  and sorting across the full selected dataset, plus scoped Clear.
- Contextual filters: OS and Computer type for Computer-related groups; Platform
  where it has a defined meaning for the selected work. These filters must be
  visible as active scope constraints, narrow to applicable matching issues and
  update counts consistently. Other item kinds cannot silently ignore them.
  Resolve the exact applicability matrix in the technical design.
- Remove Online state from the Issues operator filter set; Readiness and its
  short reason provide actionability context, and Computer inventory retains
  online-state browsing. Confidence remains available in diagnostics. These
  amend older filter requirements through the user's approval in this review.
  The earlier suggestion to remove OS/Computer type entirely has
  been revised to retain them contextually.
- Add a type-specific resolution action beside a Type/group or subgroup header
  where its work shares an appropriate decision workflow. For example,
  `Client mapping (18) — Review mappings` and `Critical (12) — Review these 12`.
  Category headings spanning several workflows keep navigation/count behavior.
  Expansion controls and resolution links are distinct controls.
- A header action opens the exact selected issue population, preserving relevant
  filters; an individual row Review opens its own decision/evidence destination.
  Reuse existing client, candidate, identity and software review pages where
  appropriate. A group workspace can provide focused comparison and supported
  decisions without claiming universal bulk-resolution capabilities.
- Resolution workspaces receive the queue's shared selection/count contract;
  they do not establish an independently maintained backlog or duplicate
  population rules. Preserve existing permissions, reasons, audit and recovery
  behavior. Return to Issues restores scope, grouping, sorting and page.

## Open challenge: operator meaning of Blocked — 2026-10-27

The user challenged the need for a separate Blocked operator category. The
integration-failure example was inadequate: a source failure is its own broad
repair task, not a justification for many independent blocked queue rows.

Code inspection finds a narrower gate: `_evaluate_unenrolled` supplies identity
signals for `device_unenrolled`, and `_device_condition_signals` marks identity
blocked for Computers participating in an active `identity_conflict`. The
shared condition engine gates applicable evaluation/execution on those signals.
This is code evidence, not a measured current production case.

This establishes a safety prerequisite but does not establish that a human has
no useful review action. Reviewing/settling identity is itself work. An engine
`may_execute` flag must not be assumed to describe human review readiness.
Existing cover links must be honored; adding new cover relationships would
require exact-scope/type design, not a presentation-only inference.

Recommendation for review: retain execution/evidence safeguards, show the
specific prerequisite and its resolution link, and reconsider whether Blocked
needs its own operator filter/subgroup. This is not yet an approved removal of
the previously discussed Readiness states. Resolve this before designing the
cross-kind readiness projection.

## Corrective proposal boundaries

- Retain the five-category, Type and Issue hierarchy, complete group counts,
  state drilldowns and direct Category entry. Present selected results close to
  their controls. A side navigation layout is one option, not a settled decision.
- Define one scope and result contract across eligible queue items before
  choosing markup: item identity, subject/client, category/type/issue, urgency,
  work state, display context, review URL and eligible actions.
- Derive counts, ordered page selection and Issues CSV from that scope; hydrate
  only selected rows. Keep affected-Computer export distinct and deduplicated.
- Apply the user-approved view modes and normal sorting above; settle remaining
  cross-kind state/status applicability decisions and the technical read contract.
- Fix the home alert's scope and label together. Keep all applicable mapping
  issue types and ensure its count matches the queue reached by the link.
- Reuse existing domain decisions and permission checks. Presentation unification
  does not authorize new mutation semantics or producer changes.
- Include the approved consolidated-store and unified-relationship scope above.
  Changes to producer persistence and relationships must be explicit in the
  reviewed migration/cutover design rather than incidental UI refactoring.

## Acceptance and evidence still needed

- Mixed entity/admin/candidate fixtures: exact group totals, filtered result
  counts, stable pages and full Issues CSV agree, including empty result scopes.
- >500 items and more than one page: all nonempty groups remain discoverable;
  no item silently disappears behind auxiliary 200-row caps.
- Independent Status/Attention/Severity and Covered tests; paused/resolved,
  missing or stale assessments, unmapped clients and inapplicable filters.
- Direct home/client/Computer/evidence links: correct scope auto-opens; filters
  survive sorting, pagination, scoped Clear and return from review.
- Permission and action tests: visible work, appropriate allowed actions,
  reason/audit requirements and safe handling of mixed item selections.
- Desktop/mobile rendered inspection of landing, expanded Category, Type/state
  refinements, critical mappings, empty results, and bulk controls.
- PostgreSQL and authenticated page measurement. S documented landing <=1 s
  and filtered <=3 s targets; current performance has not been measured here.
- Current-state documentation debt: shared governance flags
  `docs/current-state.md` as older than 90 days. It is not evidence of current
  runtime state and is outside this design correction.

## Checkpoint and next action

Latest user review: points 2, 4, 5 and 6 of the review proposal are accepted
as design direction (covered visibility, existing common store, unified
relationships, staged cutover). Consolidation definitions need context and
boundaries before acceptance. Decide Readiness removal first, then handle the
remaining original decisions individually. No implementation authorization.

Completed review (2026-10-27): [Findings review and consolidation proposal](PLAN-003-review-proposal.md)
addresses Waiting, covered visibility, all 71 registered types, the common
store, unified relationships, staged cutover, and original W1-W9/D1-D4 gaps.
It recommends removing operator Readiness altogether; this is an explicit
proposed amendment to earlier accepted filters/subgroups/columns/sorting,
not an approved change. Specific type consolidations and policy corrections
also await review. Covered symptoms should remain hidden from independent
results while valid, including when filters exclude their parent.

Written requirements and identified amendments are reconciled above; unresolved
cells remain explicit. No current deployment or browser acceptance is claimed.
Checkpoint (2026-10-27): the user-approved view, subgroup, sorting, paging,
expansion, counts, paused/covered presentation and row-layout decisions are
recorded above. Filter simplification and header resolution links are now
accepted. Cross-kind readiness semantics and the technical read
contract still need definition. Implementation is not yet approved.
The user has expanded the design to one authoritative findings store and one
covered/prerequisite relationship mechanism. Migration impact discovery and
identity/history-safe cutover design are required before implementation.
The later Ready-to-act-only selector proposals were dropped; the default is
all Open, unpaused work. Severity and Readiness remain independent.
Next: review the completed proposal and its explicit amendments, then complete
the producer/consumer compatibility ledger and exact migration/recovery design.
The common-store and relationship direction is proposed in the report;
an executable migration package and implementation acceptance remain outstanding.
A fresh session is
recommended for the next independent implementation outcome; verify this
checkpoint against Git status and current files when resuming.
