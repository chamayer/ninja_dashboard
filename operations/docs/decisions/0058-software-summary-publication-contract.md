# 0058 — Software overview summary publication contract

Status: Accepted
Date: 2026-11-11
Accepted: 2026-11-11
Plan: PLAN-056, navigation item 1 — Software

## Context

The Software overview returned its full HTML in 13.094 seconds in the approved
navigation pass. A separate release-pinned reader pass took 10.433 seconds:
title status counts 3.920 s, current-title totals 2.646 s, risk distribution
1.509 s, and other work 2.358 s. These are separate observations, not an exact
HTTP decomposition. Evidence is in the
[PLAN-056 acceptance record](../../../docs/records/PLAN-056-release-acceptance.md).

The overview and Products share `_software_page_data`, which reconstructs
fleet-level results from installations during page loading. Existing Software
title, safety and exposure publications cover part of this work, but the title
rollup lacks the current-Computer lifecycle population and its invalidation.
Moving these reads behind a process cache would leave the expensive miss path.

The user requested a contract for item 1 before implementation. This document
defines the accepted implementation obligations; it does not claim they are
enforced today or authorize migrations, runtime/test edits, external runs or a
release. Items 2–15 remain on the fixed worklist.

## Existing authority and options

Build on [DESIGN §3.8](../../DESIGN.md#38-storage-separation--four-layer-per-domain-design-2026-07-15)
and [ADR-0003](0003-four-layer-domain-storage.md): domain-owned derived state,
separate operator decisions, controlled effective reads and explicit refresh
order. Reuse accepted [ADR-0028](0028-device-software-exposure-read-model.md),
[ADR-0029](0029-software-inventory-from-complete-lists.md) and
[ADR-0030](0030-software-findings-by-desired-state-reconciliation.md), including
their amendments: complete inputs, scoped reconciliation, successful publication
boundaries, live decisions and freshness expiry. Do not reintroduce the older
finding-to-installation fan-out or override decision precedence.

[ADR-0039](0039-software-coverage-is-per-installation.md) is still marked Proposed,
although shared installation-coverage code and consumers implement parts of its
rules. [ADR-0037](0037-shared-computer-read-contract.md) is also Proposed. Use the
current shared selectors and reviewed implementation as the compatibility
baseline; neither status is silently promoted by this contract. The retained
[installed-title summary proposal](../plans/PLAN-044-page-performance.md#proposed-installed-title-summary--approval-required)
supplies useful lifecycle, initialization, isolation and recovery requirements,
but its incremental-counter storage choice is not adopted here.

Options:

- Continue request-time fleet aggregation or add page-local caches: rejected as
  the remedy for the uncached page path.
- Add independently maintained counters to every installation/decision writer:
  not the starting choice; it adds write-lock and reconciliation obligations.
- Extend existing Software background read-model publication and add the missing
  compact overview results: selected. Physical storage is selected after the
  dependency and refresh-cost review; no universal framework is introduced.

## Contract

### 1. Ownership, inputs and population

Software owns the derived title facts, risk/category results and overview
publication. Existing inventory, catalog/intelligence and classifier workflows
remain the authorities for their respective inputs. They signal changed inputs;
one Software publication owner writes a given summary. A connector or page does
not become a second writer. A summary is rebuildable derived state, not a new
product, installation, finding, decision or ownership authority.

For installation-based overview metrics, qualifying installations have the same
tenant as their Computer, `deleted_at IS NULL` and `stale_since IS NULL`.
Computers are nondeleted and satisfy the existing `current_computer_sql`
contract: nonretired; pending cleanup remains current. Do not add a recent-contact
or resolved-owner requirement to totals that do not currently have one.

Title identity retains exact stored `canonical_name` grouping. Case folding used
by decision/risk/display-name joins remains specific to those joins; do not
silently merge case-distinct title groups. Publishers retain the existing modal
selection and tie behavior where the compatibility definition uses a publisher.
Catalog products remain unscoped entities; tenant-bearing summary rows describe
the tenant's installations/results, not tenant ownership of a global product.

Finding- and exposure-based metrics retain their own populations below. They
must not acquire an installation/current-Computer predicate merely to make all
cards share one denominator.

### 2. Metric definitions and read obligations

| Overview result | Required definition | Published input / allowed read |
| --- | --- | --- |
| Installations, products | Qualifying installation rows; exact distinct canonical titles. | Software title publication; compact totals. |
| Approval/review distribution | One existing title-status bucket per qualifying title: rejected finding, then open decision prompt, then applicable global investigate decision, otherwise the existing `approve` bucket. Preserve current open/acknowledged finding predicates and modal-publisher rules. | Published title/status facts with bounded live decision overlay; compact counts. |
| Capability-categorized / uncategorized | Distinct qualifying titles with an effective capability through their installed catalog versions; uncategorized is the nonnegative remainder from products. | Catalog capability publication combined with qualifying title facts; not descriptive taxonomy. |
| Risk bands / high risk | Existing safety-band counts for published safety rows having a qualifying installation. Missing safety is unavailable/unassessed, never implicitly clean. Do not synthesize an unknown-band row where the current safety relation has none. | Existing safety model joined to published qualifying title membership, then compact distribution. |
| Active Software issues | Existing Software & security findings in open/acknowledged/investigating, excluding `whitelist_suggestion`. | Findings-owned published result with this exact predicate; not Home independent-action totals. |
| Decision-prompt titles | Distinct JSON canonical-name values in existing prompt types and active statuses; preserve current NULL/case semantics. This is distinct from pending title-status count. | Shared prompt publication; retain the different definitions. |
| Publishers awaiting decision | Distinct lowercased publishers recorded on open/acknowledged `whitelist_suggestion`/`rare_recent` findings. Preserve current empty/NULL behavior pending a separately reviewed correction. | Published prompt facts; not all installed publishers. |
| Cleanup devices | Distinct devices in the protected effective exposure view, status open/acknowledged, excluding `whitelist_suggestion`. | Existing readiness/exposure publication with live approval, access and expiry rules. |
| Weekly product count | Distinct qualifying titles with at least one installation first observed within the trailing seven days, not necessarily titles first introduced to the fleet. | Time-window summary with explicit expiry. |
| Top new product | Title with most distinct qualifying devices whose installations were first observed within seven days; canonical-name tie break. | Published time-window highlight. |
| New high-risk products | Existing high-risk safety titles with qualifying installations first observed within seven days. | Risk/title/window publication, not a new classification. |
| Recent installations | At most ten qualifying rows first observed within 24 hours, preserving existing client join, ordering and access rules. | A bounded indexed detail read is allowed; no fleet aggregate is required. |
| Human-readable names | Existing latest retained nonempty source display spelling for requested normalized keys, including retained stale rows as today; canonical fallback. | Published label lookup or indexed lookup bounded to the displayed keys. No per-page installation-wide sort. |
| Classifier configuration | Current classifier configuration and prompt enablement explanation. | Small configuration read; not a fleet summary. |

`workflow_state.user_risk_users` is currently initialized to zero without a
producer in this reader. It is not a measured user-exposure count. Preserve the
unused field only for compatibility; do not expose it as a valid KPI or invent a
producer within this contract.

The legacy `approve` title-status key means no open decision issue under the
current classification; it does not prove every installation has an explicit
approval. Human copy must say that accurately. Acceptance includes resolving
the existing misleading approval label, or explicitly approving a different
classification contract. Do not quietly substitute installation-level approval
coverage for title-status buckets or change ADR-0039's status to resolve this.

### 3. Publication and dependency contract

Reuse `software_title_current`, safety, catalog and exposure publications where
their definitions match. Correct population/maintenance gaps in their owner;
do not point consumers at a known-incompatible relation. Existing consumers and
schema shapes stay compatible unless an explicit migration review changes them.
No new materialized-view name or migration number is reserved by this document.

The implementation must register or otherwise explicitly wire these dependencies
to the publication owner, with existing Jobs coalescing and generation fences:

| Changed input | Required invalidation/publication |
| --- | --- |
| Installation insert, removal, stale/delete transition, title/version/publisher/device/client correction or relinking | Relevant title membership, totals, labels, catalog/risk joins and windows. Incomplete collection must not publish inferred removals. |
| Computer retirement, restoration, deletion, association or ownership projection | All affected installation populations and any scoped exposure/client results, even without new inventory. |
| Catalog links, capability/category evidence or rules | Affected category and title results after catalog publication. |
| CVE matches, CVE scores/KEV, threat signals, EOL and safety policy | Affected safety/risk results after successful intelligence/classification publication; unchanged match membership is insufficient to skip refresh. |
| Findings, status, relevant details, type/category/policy and classifier settings | Affected issue, prompt and title-status results; retained buckets must match current predicates. |
| Operator decisions at device/client/global title/publisher scope | Apply accepted precedence and live suppression immediately; invalidate dependent published facts. No new approval inheritance. |
| Readiness, assessment freshness, source support and time passage | Exposure eligibility remains guarded live; summary/window expiry must not await new inventory. |

Publication must consume committed, completed inputs and record the versions or
completion watermarks used. Refresh dependent components in declared order.
Publish a complete overview generation atomically; never present a newly refreshed
total alongside an old dependent distribution as one coherent result. Concurrent
input changes must remain dirty for a successor generation; publishing an older
candidate must not clear newer work or overwrite a newer generation. Duplicate
delivery must be safe. Reuse existing publication/Jobs mechanisms where possible.

Independently refreshing several matviews is not itself an atomic overview
publication. The implementation review must specify a transaction or staged
generation/publish boundary for the compact results, including failure between
component refreshes. Do not expose partially rebuilt results during bootstrap or
rebuild. Whole-view refreshes remain refresh functions, not incremental
projectors; measure their cost before selecting cadence. Never refresh full
matviews synchronously for each installation write.

### 4. Freshness, decisions and failure

**Accepted freshness policy:** ordinary overview summaries reflect a
relevant committed input change within 60 seconds, and time-window totals are
refreshed within 60 seconds of their next expiry boundary. Home's existing
60-second allowance is reused for compatible fields; Software adopts this bound
with acceptance of this contract. This policy does not shorten
source acquisition schedules or require full-fleet classification every minute.

Record `computed_at` for the input snapshot, `published_at` for successful
publication, input completion/version watermarks, oldest relevant source or
assessment freshness, and the next time-dependent expiry. Do not reset freshness
merely by serving a cached result or republishing unchanged old upstream data.
Freshness must distinguish publication lag from source/classifier lag. A
successful empty generation is valid zero; a missing/failed generation is not.

Live approval precedence, access restrictions and exposure expiry from ADR-0028/
0030 are not relaxed to 60 seconds. Decision-sensitive read results must apply
the effective decision on the next read through a bounded overlay of compact
published facts, or an equivalently consistent owner-maintained publication.
The implementation must demonstrate this without rescanning raw installations.
If the mechanism cannot do so, return an explicit unavailable/pending result;
do not silently show an old value as decision-current. Summary counts never
authorize an action, suppress a finding or replace the effective exposure view.

On producer failure, retain the last complete generation and its original
timestamps/watermarks. Mark affected values stale or unavailable when they exceed
the contract or a dependency failed. Show the time of the retained result; do
not display zero, clean, healthy, approved or fresh as an exception fallback.
Do not repair a missing/stale summary by running the fleet aggregation inside
the page request. Retry/recovery belongs to the governed background owner;
another page load must not create another rebuild. Existing Jobs status exposes
last success, failure and pending work without customer payloads.

### 5. Consumer and security boundary

The default Software overview reads protected compact results, configuration,
live effective overlays and bounded recent/detail/label rows. Split its read
path from Products so default overview requests cannot reconstruct a materialized
current-title CTE or request full-installation aggregates. Products/search/CSV
keep their own bounded/filter-specific contracts; changing their behavior is
not implied. Request-time arithmetic over compact summary rows is permitted.

Home (item 5) may reuse installation/product counts when definition, tenant,
permission and freshness match. Other consumers require the same explicit
comparison. Home governed actions are not raw Software finding counts. No other
numbered item is settled by creating this publication.

Tenant context and existing authorization apply before the read. No broadening
of the current admin-only diagnostic evidence into ordinary-user certification.
Runtime roles receive SELECT only on protected effective read surfaces, not
direct tenant-bearing matviews or publication storage. Matviews do not enforce
PostgreSQL RLS; tenant_id alone is insufficient. Require explicit DML revokes,
controlled owner/writer privileges, missing/wrong-tenant rejection and protection
against exposing client-restricted labels or rows through tenant-wide summaries.
Use regular-table RLS where applicable. Do not reintroduce retired Metabase roles.

### 6. Enforcement and acceptance

These are required implementation mechanisms, not claims of current enforcement:

| Obligation | Required enforcement/evidence |
| --- | --- |
| Sole writer, tenant isolation and protected runtime reads | Ownership/grants, explicit DML revokes, RLS/security-barrier boundary, restricted-role checks. |
| Unique grain and nonnegative totals | Reviewed unique keys/check constraints or equivalent derived-query invariants; empty/last-install cases. |
| Complete atomic publication and successor preservation | Transaction/generation boundary and existing Jobs fencing; induced failure and concurrent-change checks. |
| Every dependency and time expiry is covered | Enumerated writer/scheduler hooks and a coverage matrix; missing hooks block cutover. |
| Live decisions and no raw read reconstruction | Effective-view/decision path plus focused query-boundary and next-read correctness checks. |
| Recoverable staleness, no false zeros/freshness | Persisted success/watermarks and failure state; stale/missing/failed publication rendering checks. |

Before implementation approval, provide the exact publication storage and SQL,
writer/trigger/Job ownership, update and expiry hooks, privilege changes, bootstrap
and migration locking/order, rollback and rebuild commands, and runtime packaging.
Reconcile ADR-0039's proposed-versus-implemented state without silently changing
approval semantics. No competing producer is added as a shortcut.

Correctness validation must compare complete results against the reviewed
compatibility reader on one snapshot using small synthetic fixtures: lifecycle
and installation transitions; duplicates and case/publisher ties; partly covered
installations and decision precedence; all finding/status predicates; catalog and
risk changes; NULL/empty inputs; tenant/client isolation; exact exposure expiry;
24-hour/seven-day transitions; failed/empty/bootstrap/repeated publication;
concurrent invalidation; rollback and rebuild. New or changed test files still
require their separate approval. Do not run a fleet benchmark on the workstation.

**Accepted performance target:** default authenticated Software
overview HTML <=1.5 seconds ordinarily and <2 seconds on the bounded cold-path
check, using a completed published generation and no process-cache dependency.
This item-1 target was accepted with this contract, not before it. It does
not demand synchronous summary construction when no generation exists.
Preserve Home's already accepted target. Verify full HTTP separately from query
timing, and identify browser/external-network limitations explicitly.

Prove refresh throughput, expiry cadence and contention meet the freshness bound
in an authorized representative environment before cutover; moving expensive
work into a continuously overloaded background loop is failure. No claimed
speedup from synthetic parity alone. Initial publication/rebuild, migrations,
release and external acceptance retain their explicit authorization gates.

## Consequences and review gate

Software and compatible Home fields can share published results while detailed
queries retain their own populations. Domain semantics, completion/failure,
operator decisions and security remain authoritative. Background maintenance,
bootstrap and monitoring become required parts of the feature.

The user accepted the 60-second Software freshness bound, Software latency
target, and accurate title-status labeling on 2026-11-11. The exact live-decision
overlay and atomic publication mechanism must be concrete before implementation.
Contract approval does not authorize runtime/test/schema changes or release.
This document is the accepted contract for item 1, not proof of
implementation, enforcement, operational feasibility or settlement of the item.

## Supersedes or superseded by

Implementation note, 2026-11-11: user-authorized step 2 prepares migration 0407's
single `software_overview_current` aggregate table, its protected read view and
Software-owned refresh function. Existing title/safety/exposure publications
remain compatible. The function writes `contract_ready=false`; the protected
runtime view returns no uncertified result. No input log, receipt store or
trigger/scheduling framework is introduced. This is an implementation checkpoint,
not proof of full contract enforcement: dependency maintenance, completion
watermarks, Jobs fencing, live-read guards and certification remain steps 3–5.
Service-database migration, release and full acceptance remain separately gated.

Implementation decision, step 4 (2026-11-11): reuse the existing Jobs run,
request and dependency ledger for overview watermarks and dirty successors.
Migration 0409 revokes runtime access to the unfenced calculation function;
only a valid overview claim may call the publication wrapper. It checks input
completion before calculation, compares owner/request checkpoints afterward,
and rechecks the claim, cancellation, lease and deadline before committing.
The prior generation survives any rejection. The aggregate remains uncertified;
unknown owner history is explicitly recorded rather than invented.

Operator changes and their existing Jobs request now commit together. Queue
admission failure rolls back the source transaction instead of silently losing
an after-commit request. Safety publication follows catalog/lifecycle projection;
prerequisite failures propagate to Jobs. This changes failure handling, not
decision precedence or source authority. No input log, receipt store or new
cadence is selected. Full input-coverage/security review, reader behavior,
representative freshness proof and cutover remain outstanding.

Implementation decision, step 5 (2026-11-11): use the contract's explicit pending
option instead of introducing a second decision overlay. Migration 0410's read
function exposes metrics only from a separately certified generation whose
publication completed with the matching generation, with no newer input/request,
failed dependency or elapsed deadline. Other states expose explanatory metadata
and original timestamps without metrics/labels. The former certification-only
view is revoked from runtime roles to prevent bypassing these live guards.
The application checks tenant, the existing Software view permission and client
context before reading; no client-grained summary is invented. This does not
claim client-restricted-account certification beyond the current authority model.

The protected reader and template states are prepared, with the existing live
route preserved until acceptance/cutover review. Step 6 corrects the title-review
fallback wording to “No open decision issue”; explicit safety approvals and
classification/coverage precedence remain unchanged. Synthetic fixture switches
do not certify runtime data. Full input coverage, integration, performance and
cutover remain open. ADR-0037/0039 remain Proposed; no status is promoted here.

Implementation decision, 2026-11-12: finite W1–W4 owner coverage uses
transactional existing Jobs admission for relevant UI/admin/association writes.
One internal catalog-policy invocation calls existing local catalog, lifecycle
and matcher owners, then full classification and overview; it performs no source
fetch. Existing ownership dirtiness blocks prepared reads/publication, and the
existing scheduler drains that owner before overview work.

Overview preparation and publication share a cursor/transaction: existing
readiness and Software-owned assessment maintenance, exposure refresh and the
aggregate all roll back together. Assessment maintenance does not emit, reopen
or resolve findings. The existing Software state resource serializes overview
and classification; no input log, receipt/dirty store, service or cadence was
introduced. Owner/request checkpoints and final claim fencing still apply.
Local functional integration passed with synthetic data; worker execution used
an owner login because the development ingest role lacks a preexisting
finding_types SELECT grant. Restricted application reads were checked separately.
Runtime worker authorization and representative freshness/HTTP proof remain
certification gates; local evidence does not activate the prepared reader.

Extends the publication pattern in accepted ADR-0003/0028/0029/0030; changes none
of their decision precedence or action-eligibility rules. ADR-0039 remains
Proposed. No prior decision or other navigation item is closed by this contract.

Activation decision, 2026-11-12: collection attempts are not publication
generations. Retained inventory survives individual fetch failures. Use local
publication-owner checkpoints with the existing unconsumed reclassification
targets, ownership dirtiness and explicit operator requests. Future dependency
queues alone do not invalidate committed results. Long-running platform/matcher
work uses its completed output checkpoint; the existing findings-write guard
and dirty targets retain committed-change protection.

Overview is requested through the existing conditional workflow mechanism only
after a successful owner handler, avoiding future dependency accumulation.
Migration 0412 promotes the reviewed calculation for every successfully fenced
generation; all input/claim checks still apply. It replaces existing functions,
preserving their owners/grants. The default HTML reader selects that result;
Products/search/CSV remain unchanged. Production snapshot parity passed before
activation; full HTTP/freshness evidence must still be recorded after rollout.
No new service, store, role or cadence, and no security limitation is waived.
