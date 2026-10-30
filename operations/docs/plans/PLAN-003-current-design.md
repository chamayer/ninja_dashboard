# PLAN-003 — Issues queue current design

Status: active, design phase. Checkpoint: 2026-10-27. This consolidates the
current review direction; it is not authorization to implement, migrate,
refresh findings, commit or deploy. The registry owns plan status.

Use this document for the current contract. The
[requirements checklist](PLAN-003-issues-page-design.md) preserves historical
requirements/current-code gaps; the [review report](PLAN-003-review-proposal.md)
contains the 71-type inventory, primary conversation/commit evidence and
read-only production checks. Earlier alternatives in those documents do not
override the later decisions summarized here. Git has unrelated user work;
preserve it. No application or production changes were made for this review.

## Resolved decision: client mapping counts and status

**Decided 2026-10-29 (user):**

1. Count independent corrective actions across the dashboard and Issues, not
   stored rows and not source groups blindly. For client mapping, an entity
   finding and an admin finding for the same source group are one action (the
   local example would show 77, not 152); a group with a genuinely separate
   correction still counts separately. Both records stay visible as evidence.
2. No "pending" label or count. The approved Readiness removal already excludes
   attention/readiness states from columns, filters, subgroups and counts. Show
   Open/Paused/Resolved; when a specific action cannot run, explain it beside
   that action. Preserve assessment freshness information (whether a current
   assessment exists and its age) in details and action explanations.

Original observation and acceptance criteria, retained for implementation:

Local dev observation (2026-10-28): the dashboard's “152 critical client
mapping conflicts” combines 75 active `unmatched_source_group` entity findings
with 77 active `client_unattached_group` admin findings. Seventy-five admin
findings refer to the same source groups as the 75 entity findings; two are
admin-only. The Issues page shows 75 unresolved and 75 pending, both describing
the same 75 entity findings. Their stored state reason is
`no_current_assessment`; “pending” currently describes attention state, not a
separate workflow action.

**Resolve:** define the displayed issue identity and corrective-action
cardinality so one source-group problem is counted once across the dashboard
and Issues, then use a clear status label/action meaning for the
`no_current_assessment` state. Acceptance: counts reconcile to distinct
operator actions, and labels distinguish unresolved work from its assessment
state. Do not merge every finding of either type: admin-only groups and
independent source corrections remain separate where their scope or corrective
action differs. PLAN-004 retains cleanup of stale/overlapping resolver rows;
that cleanup is a dependency and not duplicated here.

## Joint implementation order with PLAN-004 (approved 2026-10-29)

PLAN-003 owns the foundation; PLAN-004 builds on it. PLAN-004 code may be
developed in parallel and merged when its release step arrives.

| Step | Contents | Deployment |
| --- | --- | --- |
| R0 | Identify the implementation baseline, preserve unrelated work, refresh writer/consumer inventories against HEAD. No blanket cleanup or commits | None |
| R1 | PLAN-003 additive expansion and dormant tenant-guard helper; existing writers remain compatible | Normal, after compatibility is verified |
| R2 | PLAN-003 M2–M4 coordinated cutover only | Drained maintenance window |
| R3 | PLAN-003 unified queue, counts and approved presentation changes | Normal |
| R4 | PLAN-004 foundations and simple cases (Stages A and C), then the association handoff once its prerequisites are installed. Old writers must not run while ignoring the new guard/generation protocol | Coordinated; drained if it includes the handoff |
| Operation | PLAN-004 one-time reassessment with its own reviewed application window | Separately authorized; counts as operational downtime |

Combine maintenance windows only after including all prerequisites and
successfully rehearsing the combined recovery. Moving an approved M5 change
earlier requires updating the migration/package contract so no other M5
migration ships. Each step keeps its own checks, release, push/deployment and
operation approvals. PLAN-033/034, other M5 conversions and M6 stay deferred.

## Page and interaction contract

- One Issues queue across subjects, including administrative work and eligible
  identity candidates. One authoritative findings store extends existing
  findings; candidates retain their domain storage. Preserve permissions,
  source evidence, operator decisions, history and tenant isolation.
- Five category names and current registry membership/order remain. Offer Flat,
  Category → Type, and Category → Type → Severity views. Default is grouped
  with Severity; remember the view. Severity order is Critical, High, Medium,
  Low, Info. Do not freeze an old number of registry types.
- Readiness removal is approved: no Readiness column, filter, subgroup, count
  breakdown or default-sort key. This supersedes the earlier approval of
  Readiness controls. Preserve execution/evidence guards and specific
  prerequisite/action explanations. Severity does not change merely because
  an action cannot execute.
- Ordinary entry opens one highest-severity populated path, with registry
  order for equal-severity groups. Deep links open the exact target scope.
  Ordinary rows use severity then latest detection then stable identity;
  within Severity subgroups use latest detection then identity. Software
  approval lists retain affected-Computer ordering, then detection/identity.
  Explicit sorting preserves group boundaries and covers all matches before
  paging; Flat sorting is global.
- One sibling opens at each level; no multiple-open setting. Reopening restores
  sort/page. Each expanded group/subgroup pages 50 rows independently; Flat
  has global paging. Headers expose full nonempty groups before row pagination.
- Default is independent Open, unpaused work. Paused is available through page
  summary and scoped Category/Type links: Open (18) · Paused (3). Expiry returns
  unresolved work. Retain Resolved access. Use Label (count) consistently.
- Category/Type totals and severity breakdowns use the full scoped population,
  not the page. Independent Open/Paused counts exclude covered symptoms;
  Requires-linked independent problems count separately. Covered children are
  counted under Related issues. Affected Computers is a separate impact metric.
  Fleet summaries must explicitly declare their global scope.
- Rows contain Severity, Issue, Client/Subject, concise Context with last
  detection, and Actions. Approval rows add sortable Affected Computers. Flat
  adds Category/Type context. Titles name conditions; Review is an action.
- No general row expansion. Review opens the owning workspace for evidence,
  comparisons, history and related context. Retain the specific expandable
  Related issues area for Covers/Requires, not another full issue-detail UI.
  Sharing a Computer alone does not create a relationship or extra row badge.
- Unassigned client work remains in its normal taxonomy, labeled with reported
  identity/platform and an Unassigned Client option. No invented canonical
  identities for unconfirmed observations.

## Filters and resolution scope

- Global filters: Client, Severity, Status (Open/Paused/Resolved), Search.
  Category/Type/Issue navigation remains, with equivalent selectors in Flat.
  Keep useful column sorting/filtering and scoped Clear.
- Accepted final OS/Computer-type boundary: apply these to Computer-specific
  work, not software approval groups. Approval issues show the full population
  relevant to that approval case; the proposed OS-filtered partial population
  was withdrawn. Filter scope never silently rewrites action scope.
- Platform is contextual where its meaning is defined. Complete the technical
  applicability matrix; no participating item kind silently ignores an active
  filter. Online stays in inventory; Confidence stays diagnostic.
- Provide scoped resolution links at Type/group or subgroup level where a
  coherent existing workflow exists. Review on a row targets that issue.
  Reuse client mapping, identity, software, Jobs/source and asset workspaces;
  no independently maintained resolution backlog or universal bulk resolver.
  Returning restores filters, view, expansion, sorting and page.
- Home Critical mapping issues (N) counts Critical work across applicable
  mapping types under queue eligibility. Its destination opens exactly those
  N, with Mapping · Critical · Open scope visible and results nearby. Provide
  View all mapping issues. Count and link share one selection contract.

## Root issues, relationships and assessment metadata

- One issue per proven underlying problem/corrective action. Detector fallout
  becomes impact; preserve existing symptom history with Covers where needed.
  Same Computer/vendor or correlation alone does not establish one root cause.
- Covers hides a valid symptom from independent rows even if its parent is
  filtered out. It remains evaluated and accessible through Related issues,
  detail and history. Reassess on parent changes; never auto-resolve children.
- Requires retains an independent issue with its specific prerequisite link;
  guard the affected action. Pausing a parent does not satisfy a prerequisite.
  One typed relationship mechanism supports both kinds, exact tenant/scope,
  multiple parents/chains and enforced rejection of self-links/cycles.
- Missing assessment metadata alone is not an operator task. Existing source/
  Job failure owns its repair and assessment impact. A distinct proven data or
  evaluation problem can be a finding; no new generic Waiting/Blocked bucket.
- Review all existing cover rules before conversion. Confirmed missing agents
  remain independent of offline, with unchanged severity. Correlated reporting
  loss can be covered. Pending reboot is independent or a proven prerequisite,
  not automatically covered by stalled patching or offline status.
- Collection failure can cover matching stale-observation fallout. Device
  contact and observation freshness differ; stale collection does not establish
  a new offline assertion or erase an existing independent offline problem.
- Required security agent confirmed absent on a reporting Computer: High.
  Stale telemetry does not prove protection loss. The proposed Critical rule
  was withdrawn for lack of an established evidence/policy contract.

## Consolidation boundaries

The [PLAN-004 source-record review](PLAN-004-source-record-review.md) owns
unassigned-record identity evidence, source duplicates and maintenance
predicates/actions. PLAN-003 consumes those contracts for finding subjects,
ledger cutover, Issues counts/filters/export and fleet/client prominence.
User direction (2026-10-28): unresolved identity work is Critical and shares
client-mapping prominence; strongly matched unlinked evidence is visible on the
likely Computer without asserting client ownership. Source records can require
maintenance without a Computer or client. [ADR-0048](../decisions/0048-source-record-attachment-and-cleanup.md)
accepts guarded automatic attachment and cleanup review immediately upon proven
replacement, otherwise at qualified staleness. Exact predicates and enforcement
remain with the PLAN-004 review; source cleanup stays a
separate corrective action where ADR-0043 requires it.

User direction (2026-10-29): source-record assessment does not require attachment
or client mapping. The [PLAN-004 proposed design](PLAN-004-source-record-design.md)
defines that domain workflow. Coordinate safe exact-record targets with optional
Computer/client context; do not fabricate subjects to admit unassigned work.
Shared review context does not merge independent identity, attribution, and source
correction actions. This is a design dependency, not a schema or runtime approval.
PLAN-004's [final proposal](PLAN-004-source-record-final-design.md) selects native
`source_record` and `source_record_case` mechanism subjects with durable UUIDs and
validated source references. Admit all records to independent evaluation before
identity resolution. Integrate native target/participant validators and episode
conservation with the coordinated common-store cutover; this choice remains proposed
until its ADR-0049/design approval and does not authorize migrations.

- Follow accepted ADR-0043: One machine or two? combines the five identity
  evidence types; source-record duplication and client ownership stay separate.
  Measure group/client boundaries first. PLAN-004 owns identity algorithms.
- Preserve ADR-0040 per-client name differences. Combine source-group ownership
  warnings only when exact scope and one mapping decision settle them; separate
  source corrections remain independent.
- Keep Computer without agent evidence as an inventory/lifecycle investigation
  for unexplained cases. Record expected-case dispositions; route proven
  decommissioning, identity or requirement work to its owner. Requirements apply
  to recognized OS instances, not hardware/VM shells. Do not treat legacy OS
  rows or cache labels as proof; no blanket coverage-universe expansion.
- Hudu-only Computers already have lifecycle cases under documentation_only.
  Keep per-Computer decisions and shared review context/linked assets. The
  integration-gap signal replaces zero of the measured 102 lifecycle cases;
  additional visibility is not causal repair. Actual configured-source failure
  coverage still needs separate proof.
- Preserve a verified integration-gap administrative task at its actual
  connection/decision scope, with affected clients/assets as impact. Collector
  vendor-support metadata alone is not proof of missing configuration; expected
  indirect collection gets a recorded disposition. No automatic connector work.
- Hudu archive candidates retain exact-asset decisions and safeguards; incorrect
  links are separate repairs. Same Computer is insufficient to merge them.
- One Software approval pending administrative case per product, with uncovered
  installations and rarity/recency/prevalence evidence. Preserve decision scopes
  and independent Computer/installation risks. October 14's merge request and
  later deferral are documented; migration must preserve history.
- Capability confirmation stays one product/capability judgment with combined
  evidence, separate from approval, authorization and requirements.
- Preserve independent vulnerability, support, threat and installation-path
  conditions. Approval does not automatically settle those risks. Authorization
  uses supported explicit scopes/exceptions, not vendor popularity.
- Keep patching and Windows support distinctions at their existing natural
  scopes/stages. Proven same-root fallout can be covered; no blanket family
  merge or speculative lifecycle/configuration re-graining.
- Same Job/source failure episode and repair becomes one incident issue, with
  attempts, timeout/schedule details and downstream work as impact. Ordinary
  dependency waiting is Job state; unexplained overdue processing requires
  scoped investigation, not an invented cause.
- Zero count is not retirement evidence. Each retired type needs named open
  counts, reason, replacement/disposition mapping and verification. Preserve
  history/pauses/decisions; closure means superseded, cleared or invalid only
  with supporting evidence. Otherwise keep the unresolved work reviewable.

## Bulk actions

- Offer page selection and explicit all-filtered group/subgroup selection.
  Subgroup selection never silently expands to its parent. Show scope/count,
  keep controls in the selection bar, and clear selection on scope changes.
- Remediation/policy actions require the same finding type and compatible
  eligibility/scope/permissions. A common taxonomy group alone is insufficient.
  Eligible Pause/Resume may span types; uniform software pause is an accepted
  design amendment, not a claim of existing support.
- Reuse bounded Refresh; reasoned Exclude; software approve/reject/investigate;
  explicit remote-access authorization; capability confirm/reject; identity
  merge/separate/split within each case; client ownership actions; lifecycle
  still-in-use/eligible retirement; and exact-asset Hudu archive. Source-group
  confirm/move/ignore stays in its mapping workspace. Publisher-wide effects
  and other broader scopes must be explicit. Preserve reasons/audit/guards.
- Use the normal confirmation for partial eligibility, e.g. Archive 96 assets;
  24 selected items are ineligible. Report completed/skipped/failed with optional
  detail. No extra preview page or subset-selection step. No generic bulk
  Resolve, Acknowledge or Delete. Pause/Resume stays lightweight.

## Technical package and remaining execution gates

The [technical design](PLAN-003-technical-design.md),
[consumer/alertability ledger](PLAN-003-consumer-ledger.md) and proposed
[ADR-0046](../decisions/0046-unified-findings-and-relationships.md) now specify
the following work and incorporate technical review findings R1–R4. The
second-pass review is complete; implementation and deployment remain
unapproved. Migration code, rehearsal and runtime acceptance remain
unperformed. The approved M5 alertability change for the inventory/lifecycle-
review meaning of `device_unenrolled` is to turn alertability off. Storage
conversion M1–M4 preserves current flags; M5 applies this semantic change with
its reviewed manifest.

1. Complete the producer/consumer compatibility ledger across ingest, SQL,
   state writers, ORM, participants/assessments, notifications, history,
   source targets, actions, exports and all legacy row-kind references.
2. Specify common typed subjects, stable episode identity, state authority,
   relationship-rule enforcement and shared selection/count/export contract.
   Define exact contextual-filter applicability without a partial software
   approval population. Apply reviewed accepted behavior to all queue kinds.
3. Produce explicit legacy identity/status/reference mappings and executable
   per-release migration artifacts, reconciliation queries, cutover ordering
   and rollback boundaries. Recheck occupied migration numbers at implementation.
   Keep old migrations immutable; no mass historical reopening or erased audit.
4. Produce the named current/proposed alertability list alongside type changes.
   Preserve the existing 21 eligible types, default off for new types; decisions
   do not alert. May alert is on Admin settings → Finding types. Delivery rules
   remain separate; this design enables no notification delivery.
5. Record accepted architecture in a decision record and specify implementation
   slices/affected files. Coordinate PLAN-014 applicability, PLAN-004 identity,
   PLAN-021 candidate repair and PLAN-012 shared reads. Separate measured data
   consistency repairs are backlogged, not silently included in UI work.
6. Define validation for RLS, permissions/action scope, history, pause/coverage,
   mixed subjects, >500 items, per-group pages, links/return state and matching
   headers/HTML/CSV. Browser/mobile and latency acceptance are still unverified;
   retained targets are landing ≤1 s, filtered ≤3 s.

Checkpoint: operator directions and second-pass design remedies for R1–R4 are
written. Readiness removal and the M5 `device_unenrolled` alertability change
are approved. Implementation must finish per-callsite, process-version and
gated-action inventories, plus PostgreSQL lock/privilege validation.
Implementation/migration execution and measured acceptance remain incomplete.
Bring material conflicts
back as specific decisions, rather than reopen settled choices. No execution
approval is inferred. Documentation checks are recorded in BLUEPRINT; existing
governance debt is the stale docs/current-state.md status. VERSION/CHANGELOG
remain unchanged because no release is being prepared.
