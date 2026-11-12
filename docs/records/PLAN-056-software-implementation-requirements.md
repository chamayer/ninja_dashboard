# PLAN-056 item 1 — Software contract implementation requirements

Date: 2026-11-11.
Status: Requirements gathered; implementation design and approval remain open.
Authority: [accepted ADR-0058](../../operations/docs/decisions/0058-software-summary-publication-contract.md).
Checkpoint: [PLAN-056](../plans/PLAN-056-platform-performance-assessment.md).

## Purpose and scope

Identify what implementing the accepted Software contract requires, the existing
owners involved and the evidence needed for acceptance. This is requirements
gathering, not troubleshooting, patching or selection of a storage/scheduling
design. ADR-0058 remains authoritative; this record does not amend it.

Scope is navigation item 1, the default authenticated Software overview.
Products/search/CSV retain their contracts. Home reuse requires an explicit
definition/access/freshness comparison and does not settle item 5. Items 2–15
remain open. Preserve existing uncommitted work; it is not approved implementation
or proof of deployed behavior. No runtime/test/schema or external changes made.

## Required results and semantics

Source: ADR-0058 sections 1–2; compatibility reader
`operations/apps/core/views.py::_software_page_data` and
`software_review.py::TITLE_STATUS_*`.

| ID | Result | Implementation requirement |
| --- | --- | --- |
| M01 | Installations and products | Count qualifying installation rows and exact distinct stored canonical titles. Installations and Computers share tenant; installation is neither deleted nor stale; Computer is nondeleted and satisfies `current_computer_sql`. Pending cleanup remains current. No new contact-age or resolved-owner filter. |
| M02 | Title-status distribution | One bucket per qualifying title: rejected finding, open decision prompt, applicable global investigate decision, then legacy `approve`. Preserve open/acknowledged predicates, modal publisher and tie behavior. Label the last bucket accurately as no open decision issue; it is not proof of installation approval. |
| M03 | Capability categorization | Count distinct qualifying titles linked through installed catalog versions to effective capabilities. Uncategorized is the nonnegative remainder. Do not substitute descriptive taxonomy. |
| M04 | Risk distribution/high risk | Count existing published safety rows with qualifying installation membership. Preserve existing band semantics and joins. Missing safety is unassessed/unavailable; neither clean nor a synthesized unknown-band row. |
| M05 | Active Software issues | Preserve Software & security category, open/acknowledged/investigating statuses, and exclusion of `whitelist_suggestion`. Keep the findings population independent of installation/current-Computer totals. |
| M06 | Decision-prompt titles | Preserve existing prompt types, active statuses and distinct JSON canonical-name semantics, including NULL and case behavior. This is distinct from M02's pending bucket. |
| M07 | Publishers awaiting decision | Distinct lowercased recorded publishers on open/acknowledged `whitelist_suggestion`/`rare_recent` findings. Preserve current empty/NULL predicates. |
| M08 | Cleanup devices | Distinct devices from the protected effective exposure view, open/acknowledged, excluding `whitelist_suggestion`. Preserve live approval, access, source support and freshness guards. |
| M09 | Weekly product count | Distinct qualifying titles with an installation first observed in the trailing seven days; not titles necessarily first introduced to the fleet. |
| M10 | Top new product | Most distinct qualifying devices with installations first observed within seven days; canonical-name tie break. |
| M11 | New high-risk products | Existing high-risk safety titles with qualifying installations first observed within seven days. |
| M12 | Recent installations | At most ten qualifying rows first observed within 24 hours, retaining client join, ordering and access rules. Bounded indexed detail reads are permitted. |
| M13 | Display names | Latest retained nonempty source spelling for requested normalized keys, including retained stale rows; canonical fallback. Preserve existing tie order. Lookup must be published or indexed and bounded to displayed keys. |
| M14 | Classifier configuration | Read current configuration and explain disabled prompts through a small configuration read. |

Exact canonical grouping remains separate from join-specific normalization.
Global catalog products remain unscoped; tenant summaries describe installations.
Do not promote the unproduced `workflow_state.user_risk_users = 0` field into a KPI.

## Publication, freshness and reader requirements

| ID | Required behavior | Required enforcement or acceptance evidence |
| --- | --- | --- |
| P01 | Software owns derived summaries; existing inventory, catalog/intelligence and classifier workflows own their inputs. | One named writer per summary; privilege/ownership review. Reuse matching publications and correct gaps in their owner. No competing producer or independent installation counters as a shortcut. |
| P02 | Consume committed, completed inputs in declared dependency order. | Record actual input versions/completion watermarks; distinguish a queued or failed producer from successful publication. |
| P03 | Expose a complete overview generation atomically. | Concrete transaction or staged publication boundary, including bootstrap and failures between component refreshes. Separately refreshed matviews alone do not establish this. |
| P04 | Preserve concurrent changes for a successor and prevent older candidates overwriting newer results. Duplicate work is safe. | Reviewed existing Jobs coalescing/generation fencing integration and concurrency/failure checks. |
| P05 | Reflect relevant committed changes and time-window expiry within 60 seconds. | Budget includes admission, queue wait, dependency readiness, calculation and publication. Prove representative throughput and contention; do not shorten acquisition schedules or require minute-by-minute fleet classification. |
| P06 | Apply effective decisions on the next read; retain immediate exposure expiry and access guards. | Bounded live overlay or equivalently consistent owner publication. Explicit pending/unavailable is required when a current result cannot be provided. No raw-installation rescan or 60-second decision/expiry grace. |
| P07 | Make freshness and failure explicit. | Persist snapshot `computed_at`, success `published_at`, input watermarks, oldest relevant source/assessment freshness and next expiry. Distinguish publication lag from upstream age. Retain original timestamps on failure; successful empty is zero, missing/failed is not. |
| P08 | Keep request work compact. | Separate default overview HTML from Products. No fleet aggregates/current-title reconstruction, synchronous rebuild, per-request installation-wide label sort or process-cache dependence. Configuration and bounded recent/detail/label reads are allowed. |
| P09 | Recover through the governed background owner. | Last complete generation retained; stale/unavailable UI and existing Jobs success/failure/pending visibility. Page loads do not start rebuilds or run the old aggregate as fallback. |
| P10 | Preserve tenant/client security from first query to rendered output. | Protected effective reads, explicit DML revokes, restricted owner/writer rights, regular-table RLS where applicable, missing/wrong-tenant and client-restricted checks. Runtime has no direct tenant-bearing matview/publication-storage access. No retired-role grants. |
| P11 | Preserve existing architecture and compatibility. | Separate evidence, derived state, decisions and effective reads. Do not change association authority, approval inheritance, action eligibility, other consumer schemas or ADR statuses silently. |

## Required dependency coverage and existing integration points

Each family needs an enumerated writer/hook and completion/expiry path before
cutover. The references below identify existing paths, not a claim that coverage
is complete or that triggers/new Jobs are necessarily required.

The verified [writer coverage map](PLAN-056-software-writer-coverage.md) records
the current source evidence, exclusions and locally completed W1–W4 owner wiring.
The 2026-11-12 integration evidence retains explicit role/fixture limits.
Local components exist; input maintenance is still incomplete. Do not treat the
six implementation headings as proof that these gaps or acceptance are closed.

| Input family | Results requiring maintenance | Existing integration points to account for |
| --- | --- | --- |
| Installation insert/removal/stale/delete, title/version/publisher/device/client correction and relinking | M01–M04, M09–M13; affected exposure | `ingest/inventory/software.py` apply and `refresh_read_models`; fleet/device entry points in `ingest/main.py`; catalog relinking in `software_catalog.py`. Preserve complete-list and removal-hold rules. |
| Computer retirement/restoration/deletion, association and ownership projection | Installation population and scoped exposure/client results, even with no new inventory | Shared `computer_reads.py` selector; lifecycle, `set_source_association` and ownership projection owners. Enumerate their actual output writers in the design. |
| Catalog links and capability/category evidence/rules | Category/title results after successful catalog publication | `ingest/software_catalog.py`, `software_capabilities.py`, capability operator assertions and category owner. Preserve capability/taxonomy separation. |
| CVE matches, score/KEV changes, threat signals, EOL and safety policy | M04/M11 and dependent classified/exposure results | Existing intelligence owners, `v_software_safety` refresh and classifier. Unchanged match membership must not hide changed scores/signals. |
| Findings/status/details/type/category/policy and classifier settings | M02/M05–M08 and configuration explanation | `ingest/software_reconcile.py`, `operator_job_queue.py::_software_reconcile`, Operations finding/status and policy writers. |
| Device/client/global title/publisher decisions | Immediate effective behavior plus dependent summary invalidation | `shared/software_coverage.py`, protected decision/exposure views, Operations decision UI/bulk/import paths and `software_decision_actions.py`. |
| Readiness/assessment freshness/source support/time passage | M08 live eligibility, M09–M12 time windows | `software_readiness.py`, condition/evidence owners, exposure refresh and live deadlines; background expiry path independent of new inventory. |

## Confirmed constraints relevant to implementation

Local source review only; no new external or performance measurements:

- Migration 0293's title rollup filters stale/deleted installations but lacks
  current-Computer lifecycle membership. Its existing definition cannot simply
  replace M01/M02's compatibility population.
- `refresh_read_models` commits title and safety refreshes separately, then runs
  catalog projection. This sequence alone does not satisfy P03.
- `_software_reconcile` refreshes exposure after successful classification and
  consumes only captured target generations. Reuse that successful-completion
  discipline without allowing summary publication to consume classifier work.
- Decision paths use a best-effort safety refresh and request classification.
  That behavior alone does not prove P06 for the new summary reader.
- Ordinary durable Jobs admission polls once per minute. A one-minute periodic
  request alone cannot guarantee P05 once execution time is included. The
  mechanism and cadence remain design choices; no five-second poll is selected.
- Overview/Products currently share `_software_page_data`; title-status and
  display-name helpers provide compatibility semantics. Template status copy
  currently calls the M02 fallback bucket approved.

## Decisions required before implementation approval

### Fixed implementation worklist

These six steps implement navigation item 1; they do not replace the 15-page
navigation worklist. Work proceeds one step at a time. The user authorized
step 1 on 2026-11-11 with “go.”

1. **Complete locally — separate overview HTML from Products/CSV.** Dedicated
   overview context reader and shared existing metric/detail helpers are in
   `views.py`. Products/CSV retain their existing path. This prepares the reader
   boundary; publication cutover depends on steps 2–5.
2. **Complete locally — aggregate storage and producer.** Migration 0407 adds
   one Software-owned aggregate table, protected view and refresh function;
   `ingest/inventory/software.py::refresh_overview_read_model` is the callable
   owner entry point. M01–M11 retain their populations and definitions. Results
   remain `contract_ready=false` until steps 3–5; step 2 added no automatic calls.
   Migration code was checked in an isolated synthetic PostgreSQL container,
   not applied to the development stack or production. User directed “DO 2.”
3. **Implemented locally — connect input-change and expiry signals.** Existing
   Jobs successors, operator requests and an expiry predicate
   supply the connections. Focused validation has unchanged workflow-test
   failures; the 60-second budget remains uncertified. Step 4 makes operator
   admission transactional.
4. **Implemented locally — publication boundary, watermarks and concurrency protection.**
   Migration 0409 gates publication with existing Jobs claims/completion
   revisions, preserves queued successors and records owner/request watermarks.
   Transactional operator admission and prerequisite failure propagation close
   demonstrated delivery/completion gaps. Actual synthetic Jobs integration and
   rollback/retry checks passed with recorded role/fixture limits. Runtime-role
   authorization, throughput and the 60-second budget remain uncertified.
5. **Prepared locally — immediate decisions, security and honest failure states.**
   Migration 0410 and the compact reader withhold metrics for changed decisions,
   pending/failed/expired/uncertified inputs and unsupported client context.
   Synthetic restricted-role, next-read and rendering checks passed. The live
   route stays on its existing reader pending certification and cutover review.
6. **Copy complete locally; contract acceptance OPEN.** The title-status fallback
   now says “No open decision issue.” Counts, safety approvals and decision
   precedence are unchanged. Local coverage and precise remaining gates are in
   the acceptance record. W1–W4 wiring and bounded Jobs integration are locally
   complete; runtime-role/security, representative freshness/HTTP proof and
   cutover have not been accepted.

Local implementation evidence and limitations are in the
[acceptance record](PLAN-056-release-acceptance.md).
Live aggregates remain until publication is ready. No Software latency target or
navigation-item disposition is claimed. Service-database migration, test-file
edits and external execution remain separately gated. Further contract checks and
migration/cutover remain outstanding; local step completion is not acceptance.

### Bounded change inventory — current implementation scope

This inventory records the original change obligations; the worklist and writer
map above own current completion. It does not
select new coordination infrastructure. ADR-0058 supplies the acceptance criteria;
the metric and dependency tables above supply the definitions.

| Needed change | Existing path / confirmed gap | Bounded implementation obligation |
| --- | --- | --- |
| Separate the overview read path | `views.py::_software_page_data` serves both overview and Products and reconstructs fleet aggregates. | Give default overview HTML a compact published-result reader. Preserve Products/search/CSV behavior. |
| Publish the correct title population | `software_title_current` omits the current-Computer join; the overview's compatibility SQL includes it. | Software's existing owner must publish the required cohort's results. Reuse existing publications only where their definitions match; review other consumers before changing a shared population. |
| Supply missing overview aggregates | M01–M11 mix title, findings, risk, capability, exposure and window populations. | Publish missing compact results with their existing semantics. Reuse safety, capability and protected exposure inputs; keep recent detail/configuration bounded as M12–M14 permit. Physical storage remains a design choice. |
| Connect relevant changes and expiry | Inventory/classifier/catalog/intelligence owners and decision paths exist; complete lifecycle/ownership/time coverage is not established. | Map the seven input families above to their actual existing owners and identify missing signals. Reuse Jobs requests/revisions where sufficient. Add only demonstrated missing hooks; no repository-wide trigger program is justified by this inventory. |
| Establish consistent publication | Title and safety refreshes currently commit separately; catalog follows. | Specify one complete overview publish boundary, actual input/completion watermarks, concurrent-change preservation and existing Jobs claim fencing. Separate log/receipt tables are not established necessities. |
| Preserve immediate decisions and honest failure states | Effective decision/exposure views already enforce precedence/expiry; the new summary must not weaken them. | Apply a bounded current overlay or explicit pending state on the next read; guard exposure expiry. Retain the last completed result and original timestamps; show stale/unavailable instead of false zero or fresh state. |
| Fit the freshness budget | Existing minute-based admission alone cannot guarantee a completed result within 60 seconds. | Account for admission, queueing, upstream work and publication using existing Jobs first. Select an adjustment only when the required budget and cost establish its necessity. No polling interval or new scheduler is selected. |
| Finish the reader, security and acceptance work | Existing template calls the title-status fallback approved; new publication privileges and behavior are not implemented. | Correct that label, protect tenant/client scope and effective reads, review necessary schema/privileges/packaging/recovery, and validate parity, failure/concurrency and full-page targets with the required approvals. |

Steps 2–4 now select publication storage, an atomic write boundary, metadata in
the aggregate's existing JSON field, and owner signals in existing Jobs. Live
decision/read guards are prepared; their acceptance and admission/expiry timing
proof remain outstanding.
The evidence above does not establish
a need for a separate change log, receipt store, broad trigger scheme or a new
scheduling system. Those earlier drafts are set aside, not the implementation
plan. No further troubleshooting or assessment campaign is required to identify
these changes. Steps 1–5 and step 6's wording/local acceptance review have scoped
authorization. Test edits, service-database migration, external acceptance and
cutover retain their stated gates.

### Required design deliverables

These are implementation/acceptance obligations, not additional contract terms.
The worklist and acceptance matrix record completed local components and the
remaining proof; this list does not reopen their selected mechanisms:

1. Select the minimum publication storage/SQL and identify reuse versus necessary
   extensions. Specify grain, keys/invariants, writer and existing-consumer impact.
2. Specify atomic publication and next-read decision handling, including failure,
   generation fencing and concurrent input changes.
3. Enumerate actual input writers, update/expiry hooks, completion watermarks and
   admission mechanism that can meet the 60-second budget without excess work.
4. Provide exact privilege/RLS/effective-read SQL and demonstrate the existing
   authorization model for ordinary and client-restricted callers.
5. Provide migration order/locking, bootstrap, rollback and rebuild commands,
   runtime packaging and focused validation plan. Account for both migration
   tracks; do not reserve a number from an unrelated working migration.
6. Reconcile ADR-0039's Proposed status with implemented coverage semantics while
   retaining accepted decision precedence. ADR-0037 also remains Proposed.

The earlier proposal, PLAN-056-software-overview-implementation.md,
is set aside. Its four-table layout, new admission callback, five-second interval,
and particular pending-state implementation are not selected requirements.

## Acceptance and authorization

Correctness: compare complete results against the compatibility reader on one
snapshot using small synthetic fixtures. Cover installation/Computer lifecycle,
duplicates/case/publisher ties, partial coverage and decision precedence, finding
predicates, catalog/risk changes, NULL/empty results, tenant/client isolation,
24-hour/seven-day/exposure expiry, bootstrap/failure/retry, concurrent invalidation,
older/revoked publication attempts and rollback/rebuild.

Performance: full authenticated Software overview HTML <=1.5 seconds ordinarily
and <2 seconds on the bounded cold check with a completed publication, without
process-cache dependence. Prove refresh throughput/expiry/queue contention meet
60 seconds in an authorized representative environment before cutover. Record
browser/external-network limits separately. Query speed or HTTP 200 alone does
not establish acceptance; unavailable results alone do not prove freshness.

Use focused existing checks where sufficient. New/changed tests need approval
for the specific uncovered obligations. Workstation validation is limited to
small correctness checks; no fleet benchmark, heavy rebuild or timing comparison.
Migration, initial publication/rebuild, external validation, commit, push and
deployment keep their separate authorization gates. Item 1 closes only with an
evidence-backed disposition accepted by the user.

Initial requirements gathering added documentation only. Its validation passed:
plan-registry validator (55 entries), `git diff --check`, requirements whitespace
and local links, and all three handoff size limits. These checks do not establish
runtime enforcement or SLOs; no database, HTTP or external validation was run.
