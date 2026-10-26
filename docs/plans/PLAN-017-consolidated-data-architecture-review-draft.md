# PLAN-017 — Consolidated data architecture review and target design

## Status, authority, and purpose

**Completed 2026-10-26.** Phases 1–5 ran under user approvals with two-reviewer
agreement (review Points 39–42); outcome in the
[Phase 5 triage](../records/PLAN-017-phase-5-triage.md). Follow-up work is
[PLAN-019](PLAN-019-data-pipeline-correctness-and-retention.md) (`ready`);
the retention decision is operations ADR 0045. The text below is the
charter as adopted.

Charter defined and adopted 2026-10-25. Author: Codex. Independent reviewer:
Claude. Independent review is complete; all material comments are resolved.
The user adopted PLAN-017 as the surviving identifier and authorized Phase 1,
the local static assessment. PLAN-018 is superseded with a merge pointer in the
registry. Production access, runtime changes, and execution of later phases are
not authorized by this adoption instruction. The filename retains its original
draft suffix to preserve existing links; this is the adopted charter.

This is the adopted consolidated successor to
[PLAN-017](../../operations/docs/plans/PLAN-017-data-architecture-review.md)
and [PLAN-018](PLAN-018-end-to-end-data-ingest-review.md), incorporating the
[debate](review-plan-017-018.md), especially Points 21–34 and their later replies.
Both source plans remain intact as provenance. The
[registry](../records/PLAN_REGISTRY.md) records PLAN-017 as active and PLAN-018
as superseded. Root [BLUEPRINT.md](../../BLUEPRINT.md) holds the cross-service
execution checkpoint; [assessment evidence](../records/PLAN-017-static-assessment.md)
records local findings and coverage limits.

Establish whether the platform has a coherent, trustworthy, and sustainable
data architecture from acquisition through operator results and eventual
expiry. Explain what to keep, simplify, replace, or retire, and propose a
target architecture and ordered transition where changes are justified.
Retention, recoverability, historical meaning, and total processing cost are
parts of that architecture, rather than later maintenance tasks.

The review must answer: what do we believe now, why, how fresh is it, what did
we believe then, and what can still be explained or corrected after inputs
expire? A findings register alone is insufficient. The proposed target must
connect authority, identity, evidence, decisions, publication, history,
retention, and recovery without prescribing unnecessary complexity.

## Scope and authorization

Cover all implemented data domains discovered from executable entrypoints:
clients and Computers; source observations; entities, attributes, and
relationships; CMDB; software installations, catalog, and intelligence;
patching, activities, and health; requirements, conditions, and findings;
operator decisions and configuration; notification records; Jobs, queues,
reference feeds, and maintenance. Distinguish unimplemented registry entries,
compatibility paths, retired artifacts, and verified runtime consumers.

Inspect ingest, shared code, SQL initialization/migrations, Operations models,
functions, triggers, projectors, readers, APIs, templates, exports, scripts,
and runtime entrypoints. Include packaging/migration ordering where it affects
correctness or availability of data. Follow indirect and external consumers;
retired reporting artifacts do not establish a live Metabase service.

The authorized output is an assessment, reproducible bounded diagnostics,
proposed design, and transition roadmap. This plan does not authorize fixes,
schema changes, production data changes, rebuilds, deletion, source actions,
queue manipulation, deployment, commits, or pushes. Local experiments use
synthetic data and documented disposable services; they cannot target production.

Exclude general security/compliance review, backup/disaster-recovery redesign,
infrastructure redesign, notification-delivery reliability, UX redesign,
speculative domains, and broad observability programs. Include tenant/client
integrity, structural disposability, candidate invariant checks, and the storage
and recovery-cost consequences of retained bytes. These are data-architecture
concerns, not authorization to perform disposal or redesign backups.

Previous implementation decisions may be reconsidered. For decisions governing
required guarantees or material costs, record the original problem, present
consumers, evidence, alternatives, and keep/simplify/replace/retire rationale.
Preserve needed guarantees or explicitly propose their replacement and tradeoffs.
A prior ADR does not make its physical representation or algorithm immune to
review. Unexamined decisions remain provisional, not verified. Promote adopted
durable changes to the appropriate ADR before later implementation.

## Ten architecture acceptance criteria

Apply these to operator questions and their supporting contracts. Record
satisfied, violated, or unknown with evidence and limits; these are review
criteria, not claims that the current platform already meets them.

| ID | Required assessment |
| --- | --- |
| A1 — Authority | Trace each relevant value to evidence, a selection rule, its writer, policy/reference version, and any authored override. Multiple evidence producers are compatible with one declared effective-state authority. |
| A2 — Acquisition integrity | Account for accepted, rejected, duplicate, unresolved, withdrawn, and failed input. Explain complete-empty versus partial/failed collections, pagination/caps, cursors, ordering, malformed values, and repeated input without silent loss or invented outcomes. Idempotent retries/replay do not duplicate identity, history, finding, or notification rows. |
| A3 — Lifecycle | Withdrawal, retirement, reappearance, merge/split, and reassignment preserve intended identity, useful evidence, last raw payload, temporal meaning, and action accountability. Source absence does not automatically delete canonical identity. |
| A4 — Rebuild and correction | Define and demonstrate which current/derived results can be rebuilt from retained inputs while sources are unavailable, including after permitted expiry, without losing learned identity or authored/operator state. |
| A5 — Historical truth | State the supported historical questions and horizons. Distinguish the answer published then, today's answer, and corrected processing of old evidence. Explain missing history honestly rather than infer absence. |
| A6 — Safe expiry and replay | Retention and disposal preserve referenced/protected state, replay/deduplication guarantees, and correct results during concurrent collection, reads, maintenance, and permitted replay. |
| A7 — Sustainable capacity | Assess end-to-end latency, freshness, API volume, CPU/I/O, storage, indexes, write amplification, catch-up, and maintenance at measured and projected workloads with assumptions visible. |
| A8 — Compatible transition | A proposed replacement preserves consumers and learned/authored state, has migration/publication order, parity checks, rollback limits, and evidence gates before old paths are retired. |
| A9 — Scope | Every read, write, relationship, derived copy, reassignment, merge/remap, and privileged maintenance operation follows its declared tenant/client or global-reference scope. |
| A10 — Necessary work | Avoid redundant acquisition, mutation, recomputation, and serving work; justify each retained copy and full-scope pass against correctness, freshness, recovery needs, and measured total cost. |

## Evidence and connected review outputs

Start from actual entrypoints and read/write dependencies; reconcile with
architecture authorities and ADRs. Pin HEAD, relevant dirty-source digests,
review date, and deployed version separately. Do not fingerprint or expose
secrets, private environment values, or customer records. Recheck boundaries
changed by concurrent work. An unchanged cited function alone does not prove
an earlier finding still applies: callers, SQL, configuration, data population,
policy, or deployment may have changed.

Reuse the PLAN-012 Computer pipeline findings with their baselines and scope.
Re-corroborate changed dependencies and uncertain/runtime claims rather than
repeat established work indiscriminately. Never treat local code or a historical
measurement as proof of current deployed behavior.

Create one review record under `docs/records/` with linked artifacts if needed:

| Artifact | Minimum contents |
| --- | --- |
| Object/boundary inventory | Runtime tables, views/materialized views, functions, triggers, indexes, queues, and entrypoints; purpose, grain/key, scope, owner, writers, direct/indirect readers, dependencies, lifecycle, and unknown dynamic references. Reconcile with the live catalog when authorized. |
| Authority/definition map | Relevant facts, competing evidence, source versus write authority, precedence, absence behavior, typed copies, shared definitions, authored decisions, and preventive/detective mechanisms. |
| Publication/refresh graph | Inputs/outputs, trigger, transaction, ordering/generation, invalidation including time, success/publication meaning, freshness, failure recovery, and maintenance dependencies. Include every materialized view. |
| Lifecycle/retention matrix | All dataset classes, retained units, clocks, references, coverage/expiry rules, required horizons, rebuild/replay/undo dependencies, disposal path, enforcement, owner, and cost. |
| Scenario/acceptance coverage | A1–A10 and scenarios below; traced shared contracts and domain exceptions; reviewed, unresolved, or inapplicable with evidence/reason and next action. |
| Findings and target design | Graded findings, current/target models, alternatives and tradeoffs, capacity model, candidate standing checks, and a dependency-ordered transition/routing proposal. |

Use shared IDs instead of repeating facts across artifacts. Finding fields:
ID, contract/domain, criterion, claim, evidence/reproduction, deployment scope,
impact, affected consumers, competing explanation, missing verification,
options/dependencies, verification action, and proposed owner/plan. Evidence
may be code-confirmed, runtime-confirmed, suspected, unverified, or contradicted;
retain both code and runtime evidence where available. Keep severity, likelihood,
and confidence separate. Critical denotes demonstrated data loss, contamination,
or systemic false results; High substantial wrong/missing data or unusable cost;
Medium bounded correctness/freshness/duplication/cost defects; Low definition or
documentation drift without demonstrated result impact.

Every claimed invariant names its mechanism. Distinguish prevention through
constraints/privileges/controlled writers from detection through tests/drift
checks. A passing test does not prevent every production writer from violating
a rule. Search absence alone proves neither an unused store nor missing cleanup.
Audit SQL dependencies, triggers, dynamic access, external readers, and schedules.

Inspect identity/grain, unique/composite keys, foreign keys, interval overlap,
null semantics, orphan/fan-out/double-counting risks, and actual scope enforcement
against model/migration declarations and amended ADRs. Check normalization,
units/ranges/enumerations, unknown versus absent values, timestamp/time-zone
meaning, and hard-coded thresholds/mappings/source identifiers against their
configured authority. A documented exception needs an actual enforcing or
detecting mechanism and an explicit consequence.

## Lifecycle, raw versions, retention, and recovery

Classify latest evidence and withdrawn records, raw/rejected input, material
and relationship history, immutable events, identity anchors, mappings and
operator decisions, policy/reference versions, derived state, queues/dead
letters, run logs/receipts, deduplication guards, and audit/change actions.
Each class needs its own purpose and dependencies; one window is not sufficient.

The matrix records retention authority/configuration, event/receipt/effective/
close/withdrawal/completion clocks, consumers, protected references, expiry
action, retained summaries/checkpoints, deletion scope/evidence, failure handling,
and enforcement schedule. Audit tenant/client offboarding structurally across
copies without executing deletion. Preserved identity is distinct from a
requirement to retain every associated payload forever.

Separate three things that the earlier day-only question conflated:

1. **Content fidelity and version creation.** State whether fidelity means
   complete parsed payloads, selected fields, or original transport bytes.
   Define raw equality, material
   change, volatile fields, normalization/hash/projection versions, and what
   discarded fields can no longer support. Exact raw hashes change when any
   source field changes, including poll timestamps. Material suppression saves
   history but cannot reconstruct omitted raw fields. Compare exact-content
   reuse, selective snapshots, full versions, and versioned bodies/deltas against
   the actual historical/correction questions and complexity.
2. **Chronological evidence.** A → B → A may reuse two bodies but has three
   episodes. Preserve order, validity/receipt times, withdrawal/reappearance,
   and required collection/decision evidence. Identical payload reuse does not
   make contact, receipt, or presence metadata free. Daily observed presence
   cannot become continuous presence across missing observations.
3. **Retention coverage and expiry.** Compare latest-only, last-N versions,
   a time window, a hybrid, and relevant processing/release boundaries. Define
   whether N counts unique bodies, chronological episodes, or prior versions
   plus current. Time coverage retains the state at the cutoff and subsequent
   transitions, not merely versions created inside the window. A hybrid floor
   protects the union of time-covered and last-N-required versions. Referenced
   bodies, checkpoints, decisions, and replay guards need compatible lifetimes.

No day count, N value, universal 90-day policy, or storage mechanism is selected
by this draft. Version counts bound rows per identity, not total bytes when
payload sizes, identities, metadata, and references grow. Time windows can have
high churn. Estimate costs using measured sizes/rates and visible assumptions;
compare the recovery guarantees each policy loses as well as what it saves.

For every result, distinguish a clean rebuild of today's state, reproducing
the answer published at T under its old rules, and applying corrected rules to
old evidence. State local inputs, sufficient checkpoints, code/schema/config,
authority/policy/reference versions, dependency order, and reconstruction limits.
Collector/projection version numbers or policy digests alone are not executable
history. Verify upstream historical availability instead of assuming it.

Learned identity and authored decisions are not freely recomputable caches.
Findings may carry acknowledgements, snoozes, and other operator state. The
declared reversibility baseline is [ADR-0032](../../operations/docs/decisions/0032-computer-identity-matching-and-merge.md)
(recorded, reversible merges; splitting restores memberships rather than all
intervening state) and [ADR-0040](../../operations/docs/decisions/0040-client-source-mappings-are-recorded-and-movable.md)
(recorded, movable client source mappings). Neither states an expiry. Verify
their implemented mechanisms and retained inverse-action evidence; do not
invent a blanket 90-day undo cutoff from the analytical-history purge.

Verify automatic client promotion against
[ADR-0041](../../operations/docs/decisions/0041-automatic-client-promotion.md)
and other automatic actions individually. A blanket rule that every automatic
identity action is indefinitely undoable is not established by the reviewed
repository authorities. Audit undo dependencies separately from source-data
replay, preserving sufficient prior evidence or inverse-action state for the
actual declared guarantee. Record unsupported actions and conflicts explicitly.

Prove retention/rebuild interactions using bounded synthetic scenarios. Expiry
must not orphan retained evidence, change a current value unexpectedly, erase
the only replay guard and resurrect withdrawn state, or turn "unavailable
history" into "never existed." Define cleanup batching, total job time/work
limits, resumability, concurrency scope, and verification that eligible data
actually expires. Per-transaction batching is not a bound on the entire job.

## Efficiency and physical design

Build an end-to-end cost model, tracing one acquired record and one meaningful
change through API calls, hashing/normalization, writes, queues, projections,
evaluation, reads, and cleanup. Separate steady state, burst/outage catch-up,
full reconciliation, and rebuild. Assess baseline and illustrative 2×/5× fleet
or source growth; factor in fields, installation cardinality, payload width,
change/heartbeat rates, and historical depth rather than scaling only Computers.
Treat earlier fleet counts and timings as dated measurements, not current facts.

| Dimension | Required comparison |
| --- | --- |
| Acquisition | Poll cadence versus actual change/contact needs; API pagination/caps/cursors, conditional/change feeds and selective fields when supported; cheap/frequent versus detailed/slow collection; completeness and deletion semantics under any hybrid. |
| Grain and copies | Legitimate source/entity/attribute/installation/path/version cardinality versus duplicates and join fan-out; raw/normalized/material/claim/effective/cache/facet/rollup copies, purpose and bytes/rows per fact; physical claim grain alternatives without losing per-attribute authority or invalidation. |
| Writes and computation | Required effects versus redundant mutation; contact, receipts, leases, and publication metadata included; round trips, locks, batch/set-based work, JSON/hash cost, dirty-key fan-out, repeated scans, and trigger work. |
| Invalidation and queues | Evidence, mapping, profile, policy, decision, reference, and code changes; due-time scheduling for aging/staleness/expiry; idempotency/retries, coalescing desired state without dropping distinct events, bounded backlog drains, and periodic reconciliation. |
| Serving | Shared authoritative calculations; exact population/filter/count semantics; projected columns/row width, repeated aggregates, pagination/keyset alternatives, full CSV, transfer, Python materialization/N+1, and rendering. Any extra cache needs an owner and verified net benefit. |
| Maintenance | Index/payload churn, WAL, dead tuples/HOT, table/index/TOAST growth, cleanup/vacuum, candidate partitioning/compression/settings, reference-version growth, and retained-byte effects on backup size and restore work without redesigning backups. |
| Coexistence | Runtime and compatibility consumers of legacy staging, agent-compliance, facets/caches, and refreshes; measured cost of deferred retirement; concrete simpler alternatives and migration costs before declaring redundancy. |

Do not impose "all work must be proportional to changed source data." Time and
policy alone can change results; full reconciliation may be necessary. Require
justification and measured cost for full-scope passes. Identical raw input may
normalize differently after a fix, so raw-hash equality cannot suppress all
canonical/projection updates. Cheap-looking row-count reductions can produce
wider rewrites or more read/parse work. Compare complete guarantees and total
cost, not only table count, row count, or one page's latency.

Mandatory reader sampling treats Computers and Source records separately.
For `/inventory/computers/`, cover full-fleet load, client/source/status filters,
cards/drill-throughs, later pages, and complete CSV. For Source records, measure
count, filter-choice discovery, ordered rows, and CSV independently. For other
domains, sample each distinct critical reader contract and explain coverage;
do not assume one Computer query represents every domain's behavior.

### Index contract

For each relevant index record its query or enforcing constraint, exact deployed
definition/method/predicate, key/order/coverage, scope, size, usage observation
window/reset, update sensitivity, and maintenance cost. Investigate missing,
duplicate/overlapping, apparently unused, and scope/ordering mismatches. Keep
constraint guarantees and rare operational readers in the consumer audit.
Zero idx_scan alone is not a retirement proof.

Review heartbeat-updated keys and HOT behavior per index method and changed
column, with live measurements when authorized. Compare a proposed last-seen
ordering index with write amplification, alternatives, and the existing sort
contract. A separate ordering table creates another writer/dependency; changing
the sort key changes behavior. Read speed alone does not decide the tradeoff.
Use the deployed PostgreSQL version; the repository currently declares a
version-16 image. Consult its official [HOT](https://www.postgresql.org/docs/16/storage-hot.html)
and [statistics](https://www.postgresql.org/docs/16/monitoring-stats.html)
documentation when interpreting measurements.

### Materialized-view contract

For each view record purpose/grain, scope boundary, readers, dependencies,
refresh trigger/order, input/output generations, freshness requirement,
publication/failure behavior, refresh/lock/storage/index cost, and rebuild path.
Assess keep/refresh, concurrent refresh, ordinary view, changed-key projection,
or retirement with consumer evidence. A refresh-order graph must include every
materialized-view dependency; concurrent refresh does not by itself ensure a
coherent multi-view generation.

CONCURRENTLY avoids locking out readers but has index/prerequisite and workload
tradeoffs; it does not make refresh incremental by definition or always cheaper.
Use the version-matched [refresh documentation](https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html)
and measurements. Inventory migration declarations separately from live objects.

## Scenario coverage

Assess all scenarios for applicability; trace a shared contract once with its
actual domain users, then inspect exceptions. Prioritize deeper experiments
by impact, likelihood, uncertainty, and dependency. Untraced means unresolved,
with a reason/next action, rather than passing or silently out of scope.
Trace S1, S3, S5, S8, S9, S10, S11, and S12 first; use the stated criteria for
the remaining scenarios. This orders tracing, not a mandate to run a separate
mutation experiment for every domain/scenario pair.

| ID | Scenario |
| --- | --- |
| S1 | First client and Computer in the same collection; required projections and identity dependencies. |
| S2 | Client/source-container rename, remap, exclusion, reenabling, and source-ID reuse. |
| S3 | Complete-empty versus capped, partially paged, failed, permission-limited, or malformed collection; cursor advancement and rejection accounting. |
| S4 | One source stops while other evidence persists; last-known, unknown, and withdrawn meanings. |
| S5 | Conflicting/reused identifiers, attachment, merge/split, and undo without losing decisions or scope. |
| S6 | Archived documentation with live agents; documentation-only/VM-only evidence and parent/child identity. |
| S7 | Online without trustworthy contact; late/skewed/missing times, out-of-order input, and corrections. |
| S8 | Failure around persistence, cursor update, resolution, projection, or evaluation; retry/replay of identical input and A → B → A. |
| S9 | Concurrent collectors/manual work, overlapping scopes, leasing, cancellation, and recovery; lost updates and duplicate effects. |
| S10 | Acquisition succeeds but downstream publication fails; readers and Jobs do not silently report complete freshness. |
| S11 | Policy/profile/exemption/mapping/decision/reference changes and passage of time with no new source data. |
| S12 | Tenant/client move, unassigned records, incorrect joins, global reference use, and privileged maintenance boundaries. |
| S13 | Throttling, hidden source limits, database slowdown, saturation, and outage catch-up while service continues. |
| S14 | Retention/disposal during reads, collection, replay and rebuild; cutoff baseline, withdrawn-record reappearance, reference protection, and unavailable historical answers. |

## Execution phases and gates

| Phase | Work and checkpoint | Exit/gate |
| --- | --- | --- |
| 0 — Consolidation | Write the charter, validate source/debate coverage, obtain Claude's independent challenge, resolve material comments, and record remaining decisions. | Complete: user adopted the charter on 2026-10-25; PLAN-017 survives and PLAN-018 is superseded. Source provenance retained. Only Phase 1 execution is currently authorized. |
| 1 — Static assessment | Pin baseline; enumerate objects/entrypoints; map boundaries, authorities, publication, lifecycle, consumers and scenarios; inspect relevant constraints/tests; produce code-confirmed findings and alternatives. | Every discovered path has a review destination and explicit unknowns. Save an initial assessment, an effort estimate for Phases 2–5 based on actual inventory size with coverage limits, and a bounded, aggregate-only diagnostic proposal. No live access needed. |
| 2 — Local mechanisms | Run justified bounded synthetic/disposable checks for high-risk shared contracts, invalidation, replay, scope, expiry, undo, and rebuild. Inspect existing tests before adding experiments. | Record actual checks/results and environment limits; retain reproducible instructions. A missing local environment is an explicit verification gap. |
| 3 — Authorized measurements | Reconcile catalog/deployment, reader/writer usage, integrity/drift, sizes/growth, retention, API/stage cost, queues, refreshes, locks, and full request/export timings. | Record the actual applicable production-read approval and scope; obtain approval for diagnostics outside it. Review expected cost, role/tenant, bounds/timeouts and exposure first. |
| 4 — Targeted verification | Resolve material suspected/contradicted claims and compare candidate designs with measured read/write/refresh/lifecycle costs and contract evidence. | Check each batch against existing authorization; expanded scope/cost needs appropriate approval. Preserve limitations where live verification is unavailable. |
| 5 — Design and triage | Produce coherent target/keep decisions, capacity/retention/recovery alternatives, standing-check candidates, and an ordered compatible transition/routing proposal. | Material findings have disposition/owner/next action; user questions pass the consensus gate below. Accepted future work receives its own approved scope/ADRs. |

Phases can checkpoint by contract/domain without inventing a separate blueprint
for each artifact. Keep artifacts outside BLUEPRINT; that file records confirmed
status, scope, decisions, validations, blockers, and the next resumable action.
Reconcile it with current Git state and files on takeover or session rotation.

For approved live checks use the workspace helper documented in
[operations guidance](../operations.md). Preserve tenant/runtime-role context;
privileged diagnostics do not prove ordinary readers are scoped correctly.
Use aggregate-only evidence in tracked artifacts. Review expensive exports and
EXPLAIN ANALYZE before execution; a read-only statement can still be costly.
Record data size, role, tenant, parameters, cache condition, timeout, repetitions,
and capture/deployment date. Buffer accesses are not distinct pages or direct
bloat measurements; SQL assignments alone do not quantify physical rewrites.
Separate DB execution, transfer, Python/rendering, complete request/export time,
and ingest-to-visible lag. Do not invent agreed service levels.

## Coordination and user decisions

PLAN-012 owns current inventory/population/performance implementation; PLAN-014
owns requirement policy/verdict changes; PLAN-004/015 identity implementation;
PLAN-002/005/007 related collection/Jobs/ingest work. Confirm current ownership
from the registry before routing and preserve concurrent work. PLAN-006 is
deferred and PLAN-008/011 completed in the current registry: they provide
lineage, not permission to reopen or expand work. Route new work to an approved
existing scope, a proposed new plan/backlog item, or explicit acceptance.

The old day-only Q-01 is withdrawn. Raw fidelity, historical coverage, undo,
expiry rules, and costs are open requirements to investigate, not blockers to
drafting and static assessment. Supply justified engineering recommendations.
Before asking the user a question, both active participants must explicitly
agree its exact wording, factual premise, necessity/timing, design consequence,
and understandable alternatives. Silence or a completion marker is not consent.
Reopen wording when new evidence changes it. Ask for a genuine business choice
or concrete approval at the relevant gate, not for speculative storage design.
Do not re-request an authorization already given within the applicable scope.

Return any still-open recovery/history-coverage requirements in Phase 5 as
concrete, costed alternatives across count, time, and hybrid protections.
Raise one earlier only if it actually blocks the next step and satisfies the
same question gate. An unanswered duration does not block preparing the plan
or discovering the facts needed to recommend those alternatives.

## Seed leads — to verify, not final findings

These carry concrete leads from the source plans and debate into execution.
Code-confirmed means the stated local mechanism/pattern, not its deployed use,
correctness impact, or physical cost. Recheck citations against the pinned
baseline, including concurrent changes. Suspected/search-only leads require
indirect-reader, trigger/ORM, schedule, and live-catalog reconciliation; none
authorizes a fix or retirement.

| ID | Grade and lead | Starting evidence and verification |
| --- | --- | --- |
| L1 | Code-confirmed identifiers; configuration drift unverified | Tenant `1` calls in [main.py:514](../../ingest/main.py#L514) and the binding constant in [devices.py:51](../../ingest/core/devices.py#L51). PLAN-017 A4 also seeds source IDs/URLs. Distinguish source-instance/binding identities, legitimate configuration, examples, and actual duplicate hard-coded authority without exposing private URLs. |
| L2 | Suspected parallel representations | PLAN-012's pipeline review in [BLUEPRINT.md](../../BLUEPRINT.md): Ninja staging/views beside generic observations, facets beside typed Device caches. Audit both sides' writers/indirect consumers, unique purpose, and incremental versus compatibility cost. Staging still serving a native domain is not automatically redundant. |
| L3 | Code-confirmed current-row assignments; physical cost unverified | [observations.py:151](../../ingest/observations.py#L151) and its upsert assign raw/canonical payloads on accepted newer observations. Measure heartbeat amplification; raw equality alone cannot suppress normalization/configuration/version-driven changes. |
| L4 | Code-confirmed model index; deployed cost and proposed index unverified | [models.py:3390](../../operations/apps/core/models.py#L3390) declares tenant/observed_at ordering. PLAN-012 Slice 6 in [BLUEPRINT.md](../../BLUEPRINT.md) proposes tenant/last-seen ordering for Source records. Reconcile actual indexes and weigh reader benefit against heartbeat writer/HOT cost and alternatives. |
| L5 | Code-confirmed full-pass/replace contract; cost unverified | [main.py:514](../../ingest/main.py#L514), [main.py:524](../../ingest/main.py#L524), and [evaluator.py:1961](../../ingest/evaluator.py#L1961). Compare full evaluation and replace-all verdict writes with changed-key plus due-time work, preserving finding/verdict atomicity and freshness. |
| L6 | Code-confirmed refresh statements; live graph/cost unverified | [devices.py:1047](../../ingest/core/devices.py#L1047), [custom_fields.py:224](../../ingest/core/custom_fields.py#L224), [device_health.py:275](../../ingest/core/device_health.py#L275), and [activities/ingest.py:355](../../ingest/activities/ingest.py#L355). Audit actual readers, blocking, dependency generations, and refresh alternatives. |
| L7 | Code-confirmed daily-presence writer; growth/cost unverified | [observations.py:339](../../ingest/observations.py#L339) records compact source-record/UTC-day presence. Measure actual eligible population and retention. Compare gap-preserving compression/ranges without equating observed days with continuous presence. |
| L8 | Suspected cleanup gaps, search-only | Debate Point 14 names the fourteen candidate append stores listed below. Establish actual writer activity, retention jobs/functions/triggers, lifecycle needs, and any external maintenance before claiming unbounded production growth. |
| L9 | Code-confirmed purge structure; contention unverified | [migration 0074:29](../../operations/apps/core/migrations/0074_retire_legacy_observations_and_history_maintenance.py#L29) deletes closed observation/software intervals without a row batch; [retention_observations.py:48](../../ingest/retention_observations.py#L48) loops batched claim cleanup. Verify total-job bounds, scheduling scope, protected references, and actual deployed functions. |
| L10 | Code-confirmed page cap; loss/catch-up behavior unverified | [activities/ingest.py:61](../../ingest/activities/ingest.py#L61) caps pages per source/run. Trace cursor advancement on cap/failure and outage catch-up; a safety limit must not silently skip unread events. |
| L11 | Suspected unaudited materialized-view readers | Debate Point 33's latest_device_health references are a consumer-audit lead. Start with [device_health.py:275](../../ingest/core/device_health.py#L275) and SQL dependency definitions; distinguish live readers from retained migrations and external compatibility. |
| L12 | Code-confirmed latest withdrawal metadata; complete historical coverage unverified | [observation_runs.py:186](../../ingest/observation_runs.py#L186) retains last raw payload and withdrawal/run metadata on current rows. Reappearance/new episodes can replace latest markers; audit retained material/action/run evidence before assessing repeated-withdrawal accountability. |
| L13 | Code-confirmed legacy writer/refresh paths; current execution cost unverified | [agent_compliance/ingest.py:135](../../ingest/agent_compliance/ingest.py#L135) and debate Point 30 E7. Verify schedules, source/domain use, consumers, and cost before revisiting PLAN-006's deferral. |
| L14 | Unverified diagnostic dependency | PLAN-012 references `.work/probe_plan012_observation_bloat.sql`. Before Phase 3 relies on it, review its scope/cost, sanitize and preserve reusable diagnostics under a durable tracked evidence/scripts path, and follow the live-read authorization gate. No scratch file is runtime authority. |

L8's starting candidates are ninja_core.run_log, device_snapshots, and
device_health_snapshots; ninja_activities.activities; operations.source_record_seen_daily,
change_actions, operator_job_runs, operator_job_events, job_runtime_heartbeats,
observation_snapshot_runs, source_action_requests, and source_run_queue; and
ninja_agent_compliance.alert_events and compliance_matrix_history. Schema
prefixes carry across each group only as this search inventory; confirm exact
objects and lifecycle classifications during the inventory.

## Completion and current checkpoint

Review completion requires discovered domains/objects and all scenarios to be
accounted for; A1–A10 mapped to evidence and limits; material findings routed;
and a coherent target/transition with lifecycle, index/view, efficiency, recovery,
and capacity tradeoffs. Unknowns may remain only with explicit impact, owner,
verification action, and any dependent execution gate. Do not label the full
runtime assessment verified when only static work is complete. Completion of
the review does not mean remediation or production validation is complete.

Draft validation: review agreed-scope traceability; resolve local references;
run `python scripts/validate_plan_registry.py`; check scoped whitespace and
`git diff --check`; confirm the two source plans remain unchanged. Do not add
runtime tests for this documentation-only drafting task. Record global/pre-existing
validation limitations separately from errors in these changes.

Current checkpoint (2026-10-25): Claude completed independent review in debate
rounds 12–13; R1–R8 and the final L4 line-link nit are resolved. The delivered
draft hash and original source-plan hashes were corroborated before adoption.
The user adopted this charter and authorized Phase 1 local static assessment;
registry routing is updated and both source texts remain unchanged. See root
BLUEPRINT.md and the linked assessment for the current checkpoint. Later-phase
execution, runtime changes, and production access remain outside authorization.
