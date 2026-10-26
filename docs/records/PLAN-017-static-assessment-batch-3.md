# PLAN-017 — Phase 1 third static batch

Date: 2026-10-25. Status: local static assessment in progress; Phase 1 gate
not met. This batch follows Claude round 15 and the previous checkpoint's
R01/R09/R11 source-health, R04 invalidation and R06 recovery destinations.
The [assessment](PLAN-017-static-assessment.md) routes all batches; the
[charter](../plans/PLAN-017-consolidated-data-architecture-review-draft.md)
remains the scope authority. No application imports/execution, tests,
containers, SQL execution, production access, runtime changes, commit or push.

## Baseline and round 15 dispositions

Entry HEAD is `0c812db74e9a398fbe1f32a80db85c69f216f023`. The original inventory
check reports zero changed/missing/added source files; its changed-HEAD result
is expected against the original `be55a72` baseline. All six original evidence
files remain unchanged; they are not regenerated or repinned. The two large
CSVs remain commit-time exclusion candidates only.

Claude accepted the C2 correction and F06, confirmed C1/C3–C6, and accepted U02
as unresolved. Neither the optional SentinelOne site-metadata contract nor
its deployed effects are settled by this batch. No runtime correction is
authorized or made for a stale docstring or an apparently uncalled helper.

## R09/R11 — Source run-log readers reconciled locally

### U03 — Receipt documentation and consumer lineage

The [source writer](../../ingest/source_observations.py#L151) docstring calls
its `operations.run_log` receipt an evaluator-source-guard input. That is
documentation drift: the current evaluator calls
[collection_problems](../../ingest/source_health.py#L33), which reads
`operator_job_runs` and `source_refresh_outputs`. The analogous Ninja receipt
docstring in [devices.py](../../ingest/core/devices.py#L472) also still names
the evaluator guard. Both comments are recorded here without editing runtime
code. They do not establish a current dependency.

`condition_evidence.successful_run_available` is a real successful-run SQL
reader ([definition](../../ingest/condition_evidence.py#L122)). Source search
and a Python AST name/attribute/import-reference walk found no callers in
ingest, shared, Operations apps/config, excluding tests/migrations/caches.
It therefore cannot be used as proof that the evaluator consumes source
success receipts. Static absence does not exclude reflection, external tools
or a deployed older application, and it is not retirement authorization.

The broader claim that these receipts have no current consumers is also
unsupported: the forward source-health matview still uses them and current
application SQL reads that matview.

| Forward definition | Reconciliation and status |
| --- | --- |
| Django 0061 | Original `source_health_current` and refresh coordinator. Later definitions replace the matview; its original query alone is not the current authority. |
| 0071 → 0076 → 0077 | Generic-observation replacements; 0077's `latest_run` and `latest_success` CTEs read `operations.run_log` where `kind LIKE 'source.%'`, grouped by tenant/platform. |
| 0098 | Imports 0077's `FORWARD_SQL` and changes one device-health predicate in the presence query. A local literal-only reconstruction confirmed exactly one replacement and an unchanged source-health definition suffix. No migration module was imported or executed. |
| 0093 | Inspected directly because it was named in the review lead. Its forward SQL adds lifecycle policy/audit grants/finding types and contains no run-log read. It is not evidence for that particular dependency at this baseline. |
| 0100/0134 and later inspected definitions | Replace session/v_device or other readers; no subsequent source-health replacement was found in the named local forward-definition chain. Dynamic catalog/rebuild paths and live installation still require reconciliation. |
| 0124 | Drops the `_legacy` source-health/presence pair; it does not drop the current `source_health_current` read model. |

Source-health query evidence is in [0077](../../operations/apps/core/migrations/0077_latest_reported_online_state.py#L126)
and the [0098 importer](../../operations/apps/core/migrations/0098_exclude_health_from_device_presence.py#L25).
This establishes the expected local forward definition and consumer paths,
not that any particular deployed database has applied that definition.

| Current local consumer | Receipt-dependent fields and boundary |
| --- | --- |
| Dashboard, `views.py` near 1168 | Reads platform observation time, `last_run_ok` and last-success time from the matview. Observation age is a separate dimension; a successful receipt does not force all page health indicators healthy. |
| Client workspace, `client_workspace.py` near 291 | Reads platform observation time and run result, then formats source updates; platform-level health is not a per-binding completeness receipt. |
| Patching dashboard, `views.py` near 11583 | Counts delayed sources from run failure or missing/old observation time. |
| Admin overview `_admin_health_sources`, near 18918 | Uses observed time and last run result; catches database errors without making the whole admin page unavailable. |
| Admin Data `_configured_source_data_status`, near 18952 | Uses binding-scoped Jobs successes with fallback to platform-health last-success time. This fallback can consume source-run receipts indirectly; it is not the evaluator guard's query. |
| Generic admin source-instance summary, migration 0116 | Joins `source_health_current` into source-instance status, exposing run result/count/error/success fields. Trace all resulting page/API consumers before retiring the matview. |

An empty successful collection therefore has two distinct local paths: a
source receipt feeds the expected matview/UI chain after refresh; a durable
source-refresh terminal/output feeds the current evaluator guard. Do not
replace the accepted C2 correction with the stronger, incorrect claim that
the guard reads `run_log` directly. Actual exposure/health results remain
conditional on source response, refresh order, thresholds and installed code.

Additional receipt-reader leads: `documentation_observations_overdue` reads
`source.*` successes and `software_classify_overdue` reads classifier successes,
but this source walk found no non-test Python callers for either helper.
Their docstrings alone cannot establish current startup/catch-up behavior.
The separately named `ninja_core.run_log` remains in native patch/backfill and
legacy compliance dependencies; do not combine the two run-log grains or
reopen deferred PLAN-006 merely because one Python helper is uncalled.

U03 disposition: docstring drift and uncalled-helper status corroborated;
source-run receipt consumers established at local expected-definition level;
deployed definitions/external readers remain unknown. R09/R11 own remaining
catalog/consumer verification. This is not an unused-store finding.

## R01 — Terminal source-refresh publication traced through SQL

The local call/transaction sequence is:

1. `_run_source_refresh` loads the claimed binding. For a `_FETCHERS` source
   it runs collection, then shared refresh, then returns rows, an identity or
   documentation signal, and `source_refresh.binding_id` in its result.
2. `jobs_child` emits a successful result when that execution returns without
   raising. It does not independently inspect snapshot completeness or each
   projector's returned status.
3. `jobs_worker._finish_child` first admits result workflow edges. Admission
   failure tries to finish the root as failed. Successor admission and root
   completion are separate database transactions; revision dependencies govern
   readiness rather than treating admitted work as completed work.
4. The worker invokes `operator_job_queue._finish_v1`, which calls SQL
   `jobs_finish_v1` under tenant context and the claim token.
5. The latest explicit local finish definition is in migration 0263. It checks
   tenant/context, run/token, running state, payload shape/size and nonnegative
   row count. A completed source refresh must match its result binding ID to
   its source-binding scope. It inserts the output marker, updates the run,
   releases held claims, records the terminal event and propagates dependency
   terminal state in that transaction.

Evidence: [handler](../../ingest/operator_job_queue.py#L545),
[child](../../ingest/jobs_child.py#L31), [supervisor](../../ingest/jobs_worker.py#L70),
[SQL finish](../../operations/apps/core/migrations/0263_source_refresh_contract.py#L201).
Later explicit finish replacements were not found in the inspected source;
this is not a live function-definition check.

`source_refresh_outputs` is keyed by run ID, has a tenant/binding composite FK,
RESTRICT references to run/binding, a tenant/binding/published-time index and
RLS. Its `rows_touched` permits zero or null. Output insertion is fenced and
atomic with the terminal transition, a useful preventive mechanism.

The finish function does **not** require a snapshot-run ID, inspect
`is_complete_snapshot`, reconcile expected/written/rejected counts, require
projector `status = complete`, or record a vector of actual projection
generations. Workflow revision tokens are bookkeeping for a completed producer,
not proof that every inner stage published coherent data.

F01 consequence is now code-traced through the terminal SQL: provided workflow
admission succeeds and the claim remains valid, the empty-list early return
can lead to a completed source-refresh output with zero rows. The guard's
latest terminal success and fresh output do not detect the skipped snapshot
transaction. No affected production run or permission-limited response was
observed. F04's swallowed projector failure/non-complete return state can cross
the same terminal boundary; deciding the intended completeness contract remains
its resolution task. The migration comment that incomplete source collection
cannot wake successors relies on the producer correctly reporting failure.

## R04 — Configuration, policy and passage of time

The earlier lack-of-invalidation lead cannot be promoted to a blanket defect.
Different values have different authorities and invalidation mechanisms:

| Input or change | Confirmed local mechanism | Remaining assessment |
| --- | --- | --- |
| Source material/presence/attachment | Claim projector signature includes material hash/version, schema, active state, link/entity/type/class and projection-contract version; it compares stored projection state. | Source mapping/authority versions are not part of that observation signature. Identify the responsible mutation path before expecting it to trigger a new projection. |
| Operator attribute decisions/members | SQL 0108 validates members, audits changes and queues the entity/attribute dirty key in the same transaction. Effective input hash includes decisions/members/claims and definition policy. | This mechanism covers those writers, not all configuration changes or a complete source-receipt archive. |
| Definition/field-mapping/attribute-authority registry editing | Django admin uses `ReadOnlyEvidenceAdmin` for these registries, blocking add/change/delete through those admin classes. | Do not invent a mutable-admin failure path. Privileged migrations, direct SQL and other allowed application routes must each supply their own invalidation semantics; admin read-only is not a database-wide guarantee. |
| VM guest hostname authority | Migration 0313 changes eligibility and explicitly deletes affected observation projection-state rows so the normal claim projector re-derives them. | Positive evidence of configuration-only invalidation, contradicting a blanket claim that only new source content can trigger policy updates. |
| Retired hostname authority | Migration 0329 disables hostname policies without invalidating projections, explicitly because identity naming replaced effective hostname consumption. | Verify remaining evidence/admin readers and retention meaning; do not prescribe unnecessary reprocessing from a policy-table edit alone. |
| Attribute visibility | `attribute_visibility_config` changes sensitivity and audits it. Evidence views join the definition's current sensitivity when rendering values. | A visibility change is read-time metadata, not automatically a source-value recomputation requirement. Audit all reveal/read surfaces separately. |
| Generic single/set decisions | Current attribute decisions have active/operation fields; no universal expiration field is declared on that model. | Do not impose a due-time expiry mechanism on every generic value when its contract is last-known state or persistent operator intent. |
| Finding assessment freshness, policy and snooze | Finding-state SQL separates stored attention basis from read-time policy/assessment freshness and operator handling; 0301 describes this split. | Freshness may change at read time without new source data; new assessments still need a producer. Reconcile the latest read views and scheduled passes, not just the original trigger. |
| Notification suppression expiry | `_load_suppressions` excludes expired rows using database NOW at dispatch read time. | This is a concrete time-only effect. Notification record integrity remains in scope; broad delivery reliability remains excluded. |
| Software `rare_recent` and dated reference policy | Software reconciliation captures a current time and uses it in `_recent`; new evidence is not necessary for age to change. | Scheduled whole-fleet reconciliation is a required recovery/invalidation lead, not redundant work simply because no source delta occurred. |
| Evaluation cadence | Registry declares resolver every 30 minutes, platform evaluation every four hours, plus software routine/full/inventory intervals from settings. | These are declarations, not evidence of enabled/deployed schedules, arrival/drain rates or achieved freshness. No private environment settings were read. |

Relevant source: [0313 invalidation](../../operations/apps/core/migrations/0313_vm_guest_name_not_authoritative.py#L28),
[0329 retirement rationale](../../operations/apps/core/migrations/0329_retire_hostname_authority.py#L1),
[admin restrictions](../../operations/apps/core/admin.py#L71),
[decision triggers](../../operations/apps/core/migrations/0108_attribute_effective_projection.py#L298),
[visibility route](../../operations/apps/core/views.py#L20219),
[schedule declarations](../../shared/jobs_registry.py#L821).

One rebuild input needs explicit treatment: effective selection can retain the
previous selected value under `retain_last_uncontested` when current top claims
conflict (SQL 0108, around lines 645–727). Typed caches also preserve prior values
without a new selected value. Recomputing from current claims after discarding
prior selected state may therefore answer differently from a continuing run.
This is a code-confirmed state dependency, not proof that history/checkpoints
are insufficient. R04/R08 must identify a retained baseline or replay procedure
before labeling those outputs freely disposable/rebuildable. Do not select a
new storage mechanism or history duration from this observation.

## R06 — Durable demand and publication recovery refined

Inventory apply writes installation deltas and
`software_reclassification_targets` in the same transaction. Migration 0250
defines one pending target per tenant/key/source (partial unique index) and a
pending queued-time index. These are persistent requests for classification,
not receipts that every inventory read model was published.

The consumer path in [operator_job_queue](../../ingest/operator_job_queue.py#L1080)
does the following:

1. Read the currently pending target IDs and derive title scope.
2. Run software reconciliation, which refreshes readiness, computes desired
   findings, commits per finding type, and then records condition assessments.
3. For whole-fleet scope, refresh `v_software_safety`; refresh exposure for the
   run; only then mark the captured target IDs consumed in a separate transaction.
4. Return the Jobs result. There is no claim here that the entire classification
   pass and every finding type are one database transaction.

If reconciliation or its publication fails before consumption, those target
IDs remain pending. Also, `scope_from_targets` returns whole-fleet scope for no
pending targets, not an automatic no-op. This is stronger recovery evidence
than merely the existence of a separately named full job. It still does not
prove the inventory title/catalog stages below are replayed.

| Publication stage | Inventory `refresh_read_models` | `_software_reconcile` consumer | F06 consequence |
| --- | --- | --- | --- |
| software_title_current | Refreshes first, conditional on material change in its caller | Does not refresh it | No durable title-target acknowledgement for this matview has been established. |
| v_software_safety | Refreshes after title, a separate transaction | Refreshes on whole-fleet scope, including the no-target fallback | Real reconciliation mitigation; do not claim safety can never recover. Scope/schedule and dependencies still matter. |
| Catalog and installation reference links | Runs `project_software_catalog` after matviews; catalog seeding and link batches use separate transactions | Not invoked by this consumer | Rebuilding findings/exposure is not automatically replaying catalog publication/linking. |
| EOL catalog-derived state | Tries the EOL projector, logging failures | Reference/other paths may separately reconcile | Preserve the unresolved stage-specific recovery paths. |
| Device software exposure | Published by classifier consumer | Publishes before target consumption | Persistent demand protects this consumer boundary; it is not the same acknowledgement as title/safety/catalog completion. |

F06 remains accepted with narrower stage-specific claims and these mitigations.
An unchanged inventory/empty-queue retry can skip inventory publication, while
a later reconciliation can still repair some downstream views. No permanent
loss, actual duration, or deployed stale reader result is asserted.

### U04 — Coalescing during target consumption needs an interleaving check

The producer uses `ON CONFLICT ... WHERE consumed_at IS NULL DO NOTHING`.
The consumer captures target IDs, releases that read transaction, performs
reconciliation/publication, and later consumes by ID without a generation
predicate. If another producer changes the same title during that work, its
request can coalesce into the already captured row. Whether the reconciliation
sees the new evidence and whether a subsequent job covers it depend on timing.

The current registry gives inventory jobs `software-inventory` protected keys
and classifiers `software-state`/`software-findings` keys; they are not the same
exclusive resource. SQL 0262 deliberately narrows ownership. This is not proof
that those jobs overlap in production or that no other serialization applies.
Keep U04 unresolved pending the full writer/lock/workflow audit and a bounded
synthetic interleaving check after Phase 2 authorization. Do not silently equate
pending-key uniqueness with lost-update prevention, and do not label all
coalescing unsafe. Scheduled no-target whole-fleet reconciliation may bound
effects, but its actual freshness guarantee has not been measured.

## R09 inventory correction — Global catalog schema

The original builder's qualified-name allowlist omits `catalog`; its 489-name
count is therefore explicitly incomplete for global software/reference objects.
The source-file manifest still covers the defining files. Preserve that original
evidence and builder unchanged; do not reinterpret their object count as a full
schema census. The forward-ORM inventory also cannot supply SQL-only catalog
tables through absent Django model mappings.

Supplemental local declaration destinations:

| Root SQL | Global catalog objects and contract |
| --- | --- |
| 074 | `catalog.publishers`, `products`, `software_versions`: publisher/product/version reference entities and installation-link targets; not tenant-owned Computer identities. |
| 093/106 | `capability`, `capability_source`, machine/operator assertions, capability_rule and capability_tag_rule; `v_product_capability_effective` selects dedicated authority. |
| 096 | `lolrmm_tool` public reference signals. |
| 104 | `software_category`, category_source/tag_rule, machine/operator category assertions and `v_product_category_effective`. |
| Cross-boundary references | 0250 software targets reference catalog.software_versions; installation/catalog projection, CVE matching, category/capability policy and software readers consume these objects. |

Add `catalog` to the eventual D1–D5 allowlists and retention/global-reference
audit. Do not classify absence from the old lexical CSV as absence of a runtime
store or consumer. Actual keys/FKs, protected references, retained versions,
sizes/growth and installed schema definitions remain R06/R08/R09 work.

## Coverage, limits and next action

This batch strengthens A1/A2 and S3/S10 with the receipt/output/guard distinction;
A4/A5 with explicit previous-selected-state inputs; A6/A9 with output and target
references; A7/A10 and S11 with real read-time versus scheduled recomputation;
and S8/S9 with stage-specific recovery and unresolved coalescing.
No platform-wide criterion or scenario is passed on this evidence alone.

The next static slice is the R06/R08 global catalog/reference lifecycle and
rebuild dependencies (including U04 serialization), then the remaining reader/
object/lifecycle exceptions, with an explicit closure ledger for the Phase 1
gate. U02 remains unresolved. U03 is locally reconciled as above; installed and
external consumer evidence stays gated. Re-estimate the 10–22 engineer-day
initial range after the remaining inventory reconciliation, before Phase 2.

The Phase 1 gate remains open. Exact D1–D5 queries, named executing roles for
every batch, separately named privileged D3 versus runtime D4, D4 request/export
ceilings, and Claude's review of those exact artifacts are required before any
approval request. This batch neither requests nor assumes that authorization.

## Validation

Passed: registry validation (18 entries); scoped diff/whitespace checks; local
file targets and line-anchor bounds; source AST reference inspection; literal
0098 replacement count/source-health suffix check; zero changed pinned source
files; and preservation of all six original evidence-file digests. The debate
reply records Codex round 13 and its ROUND_COMPLETE marker.

Global diff check still reports the pre-existing Operations blueprint blank line
at EOF, line 718. Root BLUEPRINT still exceeds the existing repository workflow
4,000-byte cap. No application test, SQL query, migration import/replay, runtime
request, production measurement or full governance workflow was run. No runtime
file, commit or push changed in this documentation-only assessment.
