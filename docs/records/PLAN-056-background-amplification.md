# PLAN-056 — Background amplification

## Scope and conclusion

2026-11-10: big-picture step 2, local source review after the
[shared-work map](PLAN-056-shared-work-map.md). No production commands, Jobs,
browser sessions, runtime/test edits, dependency changes or new measurements.
Existing runtime work remains preserved. This is an explanation of execution
scope and write behavior, not a measurement of current cost or causation.

**The background pipeline has incremental admission and change tracking, but
several inner stages still expand into broad computation, writes or publication.**
Consequently, few changed records or few queued Jobs do not imply little work.
Conversely, a broad refresh is not automatically avoidable: some outputs expire
with time or provide required successful-observation/evaluation evidence.

The main newly clarified boundary is Software: no pending reclassification
targets means a whole-fleet reconciliation, including for the routine handler.
This behavior is deliberate in current source and an existing test assertion;
it must not be silently changed into a no-op as a performance fix.

## How demand expands

| Starting demand | Actual expansion | Existing guard / limit | Decision consequence |
| --- | --- | --- | --- |
| One configured observation-source refresh | Collection calls the shared derived coordinator, then identity-source signals can request tenant ownership/resolver work; resolver completion can request platform evaluation. Documentation sources use CMDB successors instead. | Conditional workflow edges, same-scope queued coalescing, active-scope claim guard and resource admission. Individual projectors have dirty/batch handling. | Binding-scoped collection can lead to tenant-scoped work. Coalescing limits simultaneous pending runs, not the cost inside a run or all later reruns. Do not assume every source triggers every domain. |
| One changed software installation/title | Changed queue/fleet inventory can publish title/safety models, catalog and EOL projection, then request classification. Named-title classification narrows desired findings and active finding reconciliation. | Material-change publication/successor gates; exact title/version targets; generation-fenced consumption. | The inner readiness calculation remains tenant-wide and exposure publication remains full-model. Incremental finding scope is not end-to-end incremental execution. |
| No pending software targets | `scope_from_targets([])` returns `None`; routine `_software_reconcile` treats this as whole-fleet scope and also refreshes safety. Explicit full runs likewise use `None`. | Only an actual title list of `[]` exits before readiness/publication, e.g. pending version-only targets that map to no installed titles. A named list scopes findings; an `all` target expands them. | Do not confuse no target rows with an empty title list. Periodic untargeted work can overlap the purpose of a full-rebuild schedule, but actual cadence, coalescing and need for freshness must be established before suppressing it. |
| One identity endpoint resolution changes | Current evidence updates only differing endpoints; if any row changed, all visible open relationship-history rows joined to current evidence are updated. | Current-row equality filter; tenant/security context. History synchronization itself has no equality or changed-ID restriction. | Strong narrow write-reduction candidate: retain repair scope while avoiding writes of equal copied fields. Contribution to global history counters is unmeasured. |
| One selected relationship projection tuple | Relationship rows update only for changed input/status/selection, but evidence-support membership is deleted/reinserted for selected tuples. | Dirty tuple queue, batches, guarded relationship upserts and projection cardinality rules. | Support replacement is scoped; it is not the same population-wide history synchronization above. Measure selected-tuple membership churn before combining remedies. |
| One platform evaluation | Lifecycle/identity/coverage and other phases run over the applicable scope. Eligible requirement-state rows are deleted/reinserted even when verdict content is unchanged, with new evaluated-at time. | Scoped Computer ownership/revision checks; evaluator checkpoints; guarded whole-finding units and successful-run-only final cleanup. | Finding count returned by the run is not a count of all physical writes. Preserve successful evaluation time and finding/verdict consistency in any changed-row design. |
| One CVE matcher run, including unchanged final results | Reads installed product/version scope, snapshots existing matches, deletes tenant matches, reinserts desired matches, then compares content and refreshes safety. | Bounded CPE/CVE lookup reuse already exists; only material differences create change history and classification targets. | Downstream change suppression happens after replacement writes. Staged difference writes are a candidate distinct from computation reuse and from whether safety needs publication. |
| Repeated unchanged observations/installations | Generic observations accept newer snapshots into current state; unchanged software refreshes current last-observed/refreshed fields and open-history last-seen/received fields. Source-record software has its own evidence path. | Older/equal observation snapshots rejected; history intervals only on material/presence/contract change; inventory tracks material versus unchanged rows. | Source fidelity and freshness still require representation. No blanket inference that these writes can be removed because hashes match. Need a freshness/invalidation contract before separating heartbeat storage. |
| One decision-relevant source-record change | Admission updates subject/input version and lookup keys, enqueues the subject and affected duplicate/candidate neighbors/case keys. Assessment publishes results for its claimed batch. | Admission trigger compares material/presence/association/classification fields; companion streams excluded. Neighbor enumeration capped at 200 per key, larger buckets use case keys. Queue identity/revision coalescing and bounded SKIP LOCKED claims. | A changed record can legitimately invalidate neighbors. Observation heartbeat alone does not satisfy the reviewed admission trigger. Do not label every observation poll as a full source-record reevaluation. |

## Software scope: four distinct cases

Source: `software_reconcile.py:1209`, `:1225` and actual Jobs handler
`operator_job_queue.py:1075`.

| Pending targets / requested mode | Computed `titles` | Work |
| --- | --- | --- |
| No target rows, routine mode | `None` | Whole-fleet reconcile, tenant readiness, safety and exposure publication. |
| Explicit full mode or any `all` target | `None` | Whole-fleet reconcile, tenant readiness, safety and exposure publication. |
| Targets resolve to one or more names | Nonempty list | Scoped findings, tenant readiness, full exposure publication; this handler does not refresh safety here. |
| Targets exist but resolve to no names | `[]` | Acknowledge captured targets and exit without readiness/reconcile/publication. |

Existing `test_a_run_without_named_titles_covers_the_whole_fleet` explicitly
asserts the first behavior. The test was read, not run or modified. Settings
code defaults routine and full-rebuild schedules to 24 hours; these are defaults,
not a fresh verification of deployed schedules. The full rebuild also supplies
time/policy-driven reassessment. Candidate design must decide how that purpose
is retained if untargeted routine execution changes.

For any executed reconcile, `software_readiness.refresh` computes every
nondeleted tenant device against every registered Software finding type.
For D devices and T finding types, it prepares D × T decisions and upserts
every desired row, including assessed-at, then deletes absent readiness rows.
This is a code-derived cardinality, not a measured production count or rate.

Finding reconciliation has narrower guards: each type operates on its desired
title population and updates matching active findings' details, severity and
last-seen/detected timestamps. Assessment publication deletes missing membership,
inserts participants conflict-safely and upserts the selected assessments,
including response/currentness/evaluation timestamps. It is not a blanket delete
of every participant on every run. The readiness table is still loaded tenant-
wide by the assessment stage even when the finding scope is smaller.

Publication follows successful reconciliation: exposure refreshes as a whole
materialized model. Safety also refreshes for whole-fleet reconciliation; matcher
and changed-inventory paths publish safety separately. Multiple publication
entry points are confirmed, but redundant actual executions and their duration
are not established by this code review.

## What the queue and change guards already prevent

- `jobs_request` preserves request idempotency and coalesces compatible queued
  work by tenant/job/scope. Software admission can attach to broader queued
  classifier work or supersede narrower queued requests. That is not a promise
  to cancel a running job or eliminate all subsequent requests.
- Migration 0405 prevents a queued same-job/same-scope successor from being
  claimed while an executing predecessor exists, subject to its workflow-state
  contract. Resource limits coordinate admitted Jobs, not arbitrary page reads.
- Software inventory's `material_changed` excludes unchanged rows but includes
  new/changed/removed/relinked and source-evidence changes. It guards read-model
  refresh and classification demand; it does not stop underlying freshness writes.
- Pending Software target generations preserve changes arriving during a run.
  Only captured generations are consumed. Treat retained demand as correct
  replay protection, not automatically duplicated work.
- Source-record assessment drains a dirty queue in batches of 200, with
  revision-aware acknowledgments, five-attempt failure handling, a run time
  budget and database deadlines. Time budget is checked between batches, not
  proof every batch or whole job finishes within that budget.
- Evaluator checkpoints commit and release/reacquire the findings guard between
  units/phases after a two-second target. Checkpoints do not interrupt an active
  SQL statement or split a whole finding. Two seconds is not a proven maximum
  transaction/lock-hold duration; batch/statement costs still need observation.

## Separate required freshness from redundant content writes

1. **No freshness justification identified for equal relationship-history copied
   fields.** This UPDATE copies endpoint/resolution/authority fields, not
   successful observation times. Retaining broad repair but adding an equality
   condition is a concrete candidate; implementation and validation remain gated.
2. **Requirement and readiness timestamps have consumers.** Coverage displays
   evaluated-at. SQL exposure expiry uses the earlier of readiness and aggregate
   assessment time. Suppressing unchanged updates alone would misrepresent
   evaluation or age out actionable exposure. A replacement freshness contract
   is necessary before broader changed-row or timestamp-storage work.
3. **CVE set identity and publication freshness differ.** Matcher content
   comparison excludes recreated IDs/matched-at. Difference writes can be
   reviewed while preserving match semantics, but unchanged membership does not
   prove safety inputs unchanged: CVE metadata/scores, signals, decisions,
   installation totals and time-relative predicates also feed that model.
4. **Activity refresh can change without inserts.** All three summaries refresh
   after successful activity collection; two contain rolling 180-day windows.
   Zero inserts is insufficient to skip expiry/publication. Retention remains
   a separate product/data decision.
5. **Collection publication has mixed failure policy.** The derived coordinator
   continues after five projector-stage exceptions despite its broad completion
   invariant. Preserve the recorded authority mismatch for correctness review;
   it neither proves repeated failed work now nor authorizes removing stages.

## What this means for the recovery direction

Avoid designing one global "write only when hash changes" rule. The background
work has four different opportunities: reduce broad content replacement,
keep narrow demand narrow through preparation/publication, separate required
freshness from content churn, and avoid repeated publication while preserving
all input dependencies and expiry. These are design alternatives, not selected
architecture or a newly approved implementation scope.

The strongest write-specific mechanism remains broad relationship-history
synchronization; CVE replacement is a second concrete mechanism. Software's
untargeted fallback and tenant-wide readiness/exposure expose broader design
choices. Their actual contribution to high page latency is unknown. Earlier
global tuple counters, completed-job durations and concurrent-page observations
cannot assign per-job writes, lock waits, CPU or physical I/O to these paths.

## Minimum gaps that could change the design

| Gap | Decision it affects | Minimum useful evidence |
| --- | --- | --- |
| Frequency and size of routine untargeted/full/scoped Software runs | Keep the fallback or alter routine demand handling while retaining periodic freshness | Existing run/target metadata and actual schedule configuration, bounded and redacted; preserve uncertainty if the executed title scope was not recorded. |
| Time/rows for readiness, finding reconciliation and exposure/safety publication | Narrow inner stages, reduce refresh frequency, or leave them unchanged | One naturally occurring run with already available phase records or separately scoped instrumentation; do not infer from whole-job wall time alone. |
| Changed endpoint count versus equal open-history rows | Prioritize the narrow history equality guard versus other work | Bounded reviewed read-only comparison and existing deployment-definition confirmation, before any candidate mutation. No population-wide write or benchmark needed to prove the mechanism. |
| Material CVE deltas versus replacement population | Justify staged difference persistence and its scope | Existing match-count/change-history/run metadata over a comparable natural run; no forced full matcher pass on the workstation. |
| Waits, spills and I/O overlapping page requests | Choose read work, write work, concurrency or capacity as the first platform priority | Big-picture step 3; existing-role visibility is currently insufficient for some fields. Another uncorrelated global counter sample will not resolve it. |

These are the gaps to consider, not an authorization to run all listed probes.
No further browser/cold/Coverage replay is needed for this explanation.

## Checkpoint and source references

Big-picture step 2 is complete as a static amplification review. **Next is
step 3: establish resource interaction** using retained evidence first, then
define only the bounded observations capable of distinguishing contention,
I/O/spills and expensive independent reads. Do not claim the 12-item assessment
complete or select infrastructure/scheduling changes from this map.

Sources: `ingest/operator_job_queue.py:_admit_workflow`, `_run_source_refresh`,
`_software_reconcile`; `shared/jobs_registry.py` workflow/schedule definitions;
`software_reconcile.py:scope_from_targets`, `pending_scope`, `_run`,
`reconcile_type`, `write_assessments`; `software_readiness.py:refresh`;
`inventory/software.py:ApplyResult.material_changed`, `HISTORY_SQL`, `CURRENT_SQL`,
`refresh_read_models`, `refresh_exposure_read_model`; `intel/matcher.py:run_once`,
`_match_and_upsert`; `relationships.py:resolve_current_evidence`, `project_all`;
`observations.py` snapshot guard/current upsert; `source_records.py:assess`,
`_claim`, `_acknowledge`, `flush_assessments`; `evaluator.py:_EvaluationBatches`,
`_write_requirement_state`; migrations 0223/0263/0405 (Jobs), 0370/0397
(record admission), 0395 (relationship projection), 0332 (requirement writer);
SQL 068/114 (moving activity windows and exposure expiry). Relevant source
functions match HEAD; earlier local runtime edits remain outside this analysis.

Validation: current source/HEAD comparisons, existing assertion review,
registry, whitespace and blueprint-size checks. No tests executed or changed;
no runtime or performance claims beyond the retained evidence.
