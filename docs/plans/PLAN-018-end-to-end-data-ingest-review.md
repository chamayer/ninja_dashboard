# PLAN-018 — Independent end-to-end data and ingest architecture review

## Status and objective

Ready. Defined 2026-10-23. Review execution has not started.

This is an independently authored plan. Keep PLAN-017 intact. Comparison,
combination, and selection wait for the user's explicit instruction.

Validate the platform's data architecture strictly for data integrity,
performance, and avoiding unnecessary duplication from ingest through readers.
Determine whether facts are complete, valid, consistently interpreted, stored
with clear authority, and processed efficiently. Propose dependency-ordered
remediation backed by code and measured data.

At every boundary ask: is the data correct, is this copy or calculation
necessary, can it drift, and what does it cost to write, refresh, and read?

## Scope and boundaries

Cover the data paths of all implemented domains discovered in the repository:
Computers, clients, generic entities/relationships, CMDB, software
installations/catalog/intelligence, patching, activities, device health,
requirements, conditions, findings, notification records, configuration, and
operator decisions. List registered but unimplemented domains separately. Verify
runtime, compatibility, and retired status instead of assuming use from code.

Inspect `ingest/`, `shared/`, SQL initialization/migrations, Operations models,
migrations, functions, triggers, APIs, readers, templates, exports, operator
scripts, and runtime entrypoints. Inspect packaging or migration ordering only
where it can change data correctness or performance. Include discovered external
consumers; retired reporting artifacts are compatibility evidence, not an
assumed live service.

Review artifacts and bounded diagnostics are in scope. Fixes, migrations,
rebuilds, deployment, queue changes, and source-platform actions are follow-up
work. Existing authorization for relevant production reads persists; record
each diagnostic's scope and expected cost. Materially expanded access and
production mutations remain separately controlled. Comparison with PLAN-017
waits for the user.

Excluded: general security/compliance review, credential rotation, backup and
disaster-recovery assessment, infrastructure redesign, broad observability or
service-level programs, notification delivery reliability, speculative future
domains, and general code quality. Examine tenant/client scoping, concurrency,
retries, and partial failures only for their direct effect on data integrity,
duplication, freshness, or processing cost.

## Method and evidence

Start from executable entrypoints and actual read/write paths, then reconcile
them with declared architecture and decisions. Existing reviews are leads to
corroborate. Trace indirect dependencies: a compatibility column may depend on
a projection described as a shadow by an outdated comment.

Pin the repository commit and relevant dirty-file digests at each checkpoint;
record deployed version separately. Distinguish committed, working-tree, and
deployed findings. Preserve other agents' work and recheck changed boundaries
before finalizing conclusions.

Maintain two connected ledgers:

- Boundary: producer, consumer, owner, identity/grain, tenant/client scope,
  schema, event/contact/collection/receipt times, completeness, transaction,
  freshness, retry/failure behavior, and enforcement mechanism.
- Object: every runtime table, view, materialized view, function, trigger,
  index, and queue; classification, writer paths, indirect readers,
  dependencies, retention, rebuild source, and retirement status.

Enumerate objects and entrypoints; reconcile static inventory with the live
catalog when available. Explain unmatched objects and unresolved dynamic
references. Trace each distinct contract and every domain-specific exception.
No reader found by search is a lead, not proof of an unused store.

## Resumable execution

| Step | Work and output | Completion criterion |
| --- | --- | --- |
| 0 | Establish baseline, domains, data entrypoints, object inventory, and concurrent changes. | Every discovered data path has a review destination; unknowns are explicit. |
| 1 | Review collection completeness, normalization, and value validity per connector, reference feed, snapshot, event, and on-demand path. | Pagination, caps, cursors, time semantics, malformed values, completeness/withdrawal rules, and duplicate input handling are explained. |
| 2 | Trace evidence through client/identity resolution, links, canonical entities, attributes, caches, relationships, current state, and history. | Grain, authority, precedence, provenance, identity stability, deduplication, timestamps, and enforcement are explicit. |
| 3 | Trace data processing order and repeated/concurrent/partial runs. | Transactions, dirty queues, refresh dependencies/generations, invalidation, and idempotency prevent incomplete, stale, duplicated, or overwritten results. |
| 4 | Reconcile policy/verdicts, decisions, findings, pages, APIs, search, and exports. | Definitions and selected membership agree; readers consume authoritative calculations; scoped counts/lists/exports reconcile. |
| 5 | Audit duplicated storage and calculations and verify structural integrity. | Every copy has a purpose and refresh contract; redundant/unused stores and drift are evidenced; constraints, keys, joins, and scope preserve correct relationships. |
| 6 | Measure freshness, collection cost, storage/write cost, and reader performance. | Ingest-to-visible latency and stage costs are measured or explicitly unmeasured; Computers and Source records have separate page-specific evidence. |
| 7 | Apply the data scenario matrix, reconcile documentation, and produce findings and target design. | Every domain/scenario has a disposition; remedies address integrity, performance, or unnecessary duplication and are evidence-backed and routed. |

Each step can stop after saving ledgers, findings, validation, and next action.
Steps 0–5 can advance without live access; runtime assertions stay unverified.
Diagnostic needs can be identified early, but a query timing does not replace
an end-to-end page or ingest measurement.

## Required boundary questions

### Acquisition and completeness

Distinguish complete empty results from partial pagination, source limits,
permission loss, failed enrichment, and outages. Determine when snapshots may
withdraw records and cursors may advance. Review overlap windows,
duplicate/out-of-order events, source-ID reuse, renamed containers, timezone
ambiguity, clock skew, missing fields, malformed values, and new record types.

Validate units, ranges, null versus unknown, normalization consistency, and
invalid-value handling. Identify hard-coded sources, thresholds, and mappings
that disagree with configured authority or drop otherwise valid data.

Account for accepted, rejected/quarantined, duplicate, unresolved, withdrawn,
and failed records. Find silent drops and hidden limits. Check that replaying
the same input cannot invent identities, history, or finding/notification rows. Check raw-payload
fidelity against normalization and material-change hashes.

### Authority, state, and history

For names, serials, client scope, OS, role, type, online state, contact,
lifecycle, coverage, patch state, and software identity, trace inputs and
copies. Identify selected authority, conflict handling, and absence behavior.
Include operator corrections, exemptions, merge/split, and reassignment.

Distinguish polling from contact, source presence from canonical membership,
and current state from history. Check intervals, heartbeat behavior, late
corrections, provenance, and reproducibility with the original policy and
configuration version.

### Execution and change propagation

Trace first collection of a new client and Computer, including whether
resolution precedes required projections. Establish whether success means
acquisition, persistence, or completed publication. Identify partial commits,
swallowed failures, stale caches, and unbounded drains. Determine whether
source, mapping, policy, profile, exemption, and decision changes invalidate
all dependent results without requiring new upstream input.

Review repeated and concurrent work for duplicate rows/history, lost updates,
incomplete publication, and unnecessary reprocessing. Check that collectors
and projectors finish in an order that gives downstream readers complete data.

### Duplication and structural integrity

Catalogue copies of the same facts across raw payloads, normalized records,
canonical fields, typed facets, caches, materialized views, rollups, legacy
stores, and reader calculations. Classify each as necessary source evidence,
history, justified optimization/compatibility, or potentially redundant.
Multiple records or layers are not automatically duplication defects.

For each derived copy, require a defined purpose, owner, consumer, refresh and
invalidation path, consistency check, and measurable cost. Audit direct and
indirect readers before calling a store unused. Determine whether one
authoritative calculation can replace copied policy logic.

Verify unique/composite keys, foreign keys, constraints, null handling,
orphans, cross-client/tenant joins, source-record identity, and relationship
cardinality. Test join fan-out, double counting, and merge/reassignment effects.
Check that effective constraints match model and migration declarations.
Assess migrations only where ordering or transformations affect integrity.

### Performance, capacity, and freshness

Measure collection duration/API volume, queue age, stage lag, WAL/index churn,
dead-tuple/HOT statistics, table/index/TOAST sizes, autovacuum, retention growth,
refresh work, locks/waits, and resource contention. Distinguish mechanisms
from suspected causes; buffer accesses are not unique pages or a direct bloat
measurement.

For `/inventory/computers/`, measure full-fleet load, client/source/status
filters, card destinations, later pages, and complete CSV. Attribute time to
canonical reads, Hudu/source evidence, verdicts, aggregates, transfer, Python
processing, and rendering. Measure Source records separately, including count,
filter-choice discovery, ordered rows, and CSV. Sample other critical readers
per domain and explain why the sample covers their contracts.

Record workload, role, tenant, data size, cache condition, timeouts, and
repetition. Check diagnostic cost before EXPLAIN ANALYZE or full exports.
Assess query/index/storage proposals against writer and refresh costs as well
as read speed. Include full versus incremental work, unnecessary API refetches,
repeated scans, N+1 queries, payload width, unbounded Python materialization,
filtering after aggregation, pagination, and database-to-application transfer.
Assess retention and growth for query/write cost and preserving necessary
history. Use measured baselines; do not invent agreed service levels.

## Scenario matrix

Trace applicable scenarios through the boundary ledger. Use synthetic data or
disposable local services for data-mutation experiments.

1. New client and new Computer in one collection.
2. Client/source group rename, remap, exclusion, and reenabling.
3. Complete empty snapshot versus partial/failed/permission-limited collection.
4. Source outage while other sources report the same entity.
5. Duplicate/conflicting/reused identifiers, merge, and split.
6. Archived documentation with live agents; documentation-only/VM-only evidence.
7. Online without trustworthy contact time; late/missing/skewed timestamps.
8. Partial failure before/after persistence, cursor advancement, resolution,
   projection, and evaluation, followed by rerunning the same data.
9. Concurrent collectors, manual refresh, overlapping scopes, and lease recovery.
10. Projection/evaluation failure while acquisition succeeds.
11. Policy/profile/exemption/decision changes without new source input.
12. Tenant/client reassignment, unassigned records, and incorrect-scope joins.
13. Backlog surge, throttling, slow database, and saturation.
14. Retention expiry, historical corrections, and recomputing derived state.

## Findings, deliverables, and completion

Grade claims as code-confirmed, runtime-confirmed, suspected, unverified, or
contradicted. Each finding records ID, domain/contract, grade, impact,
severity, evidence/reproduction, deployment applicability, affected readers,
competing explanation, missing verification, remedy options, dependencies,
validation, and proposed owner/plan.

Severity: Critical for demonstrated data loss, scope contamination, or systemic
false results; High for substantial incorrect/missing/duplicated data or
unusable performance; Medium for bounded correctness, duplication, freshness,
or performance weaknesses; Low for data-definition/documentation drift with
no demonstrated result impact.
Record likelihood separately from severity and evidence confidence.

Deliver a review record under `docs/records/` containing:

- System map and acquisition/refresh graph, including policy, decision, and
  Jobs feedback paths.
- Object/boundary/authority/definition/reader-writer ledgers and coverage matrix
  identifying reviewed paths and unknowns.
- Findings register and reproducible aggregate-only diagnostic references.
- Assessment of what holds, what fails, justified duplication, and the
  smallest coherent target design, with alternatives and tradeoffs.
- Remediation roadmap ordered by dependencies and impact for data integrity,
  performance, unnecessary duplication, and obsolete storage/calculations;
  include write/refresh/read costs and verification per proposal.

Complete when all discovered domains/entrypoints are accounted for, major
claims have evidence/deployment scope, every scenario is reviewed or explicitly
unresolved/inapplicable, and material findings have routing and next action.
Keep access and validation limitations visible. Review completion does not
imply remediation completion.

## Coordination, validation, and checkpoint

PLAN-017 remains separate. PLAN-002/005/007 own related ingest/Jobs changes,
PLAN-004/015 identity, PLAN-006 legacy compliance, PLAN-008 retired reporting,
PLAN-012 inventory readers/performance, and PLAN-014 requirements. Confirm
current ownership before routing findings; do not expand another plan.

When execution starts, root `BLUEPRINT.md` holds the active checkpoint and
points here; detailed evidence belongs in the review record. Use the documented
helper for authorized live checks. Preserve private records outside tracked
artifacts. Validate registry structure, references, and scoped whitespace for
planning changes; use proportional checks during execution.

Current checkpoint: independent plan drafted and narrowed on 2026-10-23 to
data integrity, performance, and avoiding unnecessary duplication. No review execution,
new production reads, runtime edits, migrations, commit, or push. Next action:
retain separately and await the user's instruction before comparison,
combination, or review execution.
