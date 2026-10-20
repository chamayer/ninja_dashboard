# Unified Jobs handler and execution-path audit

Status: source-level discovery; adapters and safety contracts are not implemented.
Baseline: `e6bc64b`. No production handler was executed for this audit.

The machine-checked evidence is `shared/jobs_inventory.json`, schema version 2.
Its records retain callable expressions, scheduler options and enclosing
conditions, HTTP methods/prefixes/aliases, thread owners, startup calls,
admission/follow-up calls, catalog metadata, diagnostic producers, and relation
consumers. Source configuration expressions are recorded, not evaluated or
copied from private environment values. The test excludes tests and historical
migrations; the latter still need SQL dependency review.

## Interpretation shared by every entry

- Owner below means the code module responsible for execution, not a person.
- All 30 durable dispatch keys appear exactly once in the current static
  catalog and dispatcher mapping. This is not parity with every execution
  path: HTTP wrappers, startup, domain queues, and follow-ups also exist.
- Durable execution currently shares one process-local two-slot semaphore.
  The active `(tenant, job_key)` unique index coalesces demand; Software modes
  have additional family exclusion/supersession. Direct HTTP/thread execution
  bypasses that semaphore. Neither is a deployment-wide resource contract.
- There is no unified cooperative cancellation checkpoint or absolute Job
  deadline. A 90-minute renewable heartbeat lease is not a runtime limit.
  No handler is certified kill-safe or automatically retryable. These are
  **unreviewed**, not an assertion that every handler is non-idempotent.
- Existing outcomes mix counts, booleans, `None`, diagnostics, and swallowed
  failures. No returned count is a material revision or a complete result
  contract. A future adapter must identify required steps and acknowledge
  each result before its parent can complete.
- Source/client-scoped demand can invoke tenant-wide projectors. Preserve
  broad exclusion until the actual writes are scoped; API input scope alone
  is insufficient evidence of independent execution.
- Maximum observed successful durations below are from the retained aggregate
  sample in `job-measurements.md`, not current runtime measurements or proposed
  deadlines. A dash means no completed-job estimate in that sample.

## Durable dispatch audit

All callable names in the table resolve through `ingest/operator_job_queue.py`
`_execute`; exact expressions and advertised stages are in the snapshot.
`main` means `ingest/main.py`. Cadences and enablement conditions are retained
per registration under `evidence.schedules`; absent scheduler registration
means operator/dependency-only today, not an invented schedule.

| Key | Owner / callable | Current effects and prerequisite/result caveat | Maximum seconds |
| --- | --- | --- | ---: |
| `patches` | main / `run_patching_once` | Ninja org/location/policy/device/health/custom-field/patch/activity writes, derived refresh, Windows servicing. Advisory cycle lock; `False` means skipped but the dispatcher converts it to zero. `_safe` hides substep failures; `True` does not prove complete collection. | 531.7 |
| `agent-observations` | main / `run_agent_observations_once` | Identity-source observations, conditional resolution, shared derived refresh. Per-source collection errors and resolver errors can be swallowed below the wrapper. | 354.0 |
| `documentation-observations` | main / `run_documentation_observations_once` | Non-identity observations, derived refresh, CMDB findings. No enabled source returns normally; collector and CMDB errors can be nonfatal. | 157.8 |
| `resolver` | main / `run_identity_resolver_once` | Client resolution, device/observation identity resolution, optionally current-state refresh. Both drain exceptions are logged and swallowed; returns `None`. | 70.5 |
| `platform-evaluate` | `ingest/evaluator.py` / `evaluate` via main alias | Reads current projected state/source guards; updates findings and diagnostics. Durable path calls the lower-level function; direct HTTP wrapper swallows exceptions. | 472.6 |
| `patch-classify` | `ingest/patch_findings.py` / `classify` via main alias | Reads patch/decision state and writes findings plus run diagnostics; needs a completed patch/projector revision, not just recent wall-clock time. | — |
| `parity-check` | `ingest/parity_check.py` / `run` via main alias | Writes `operations.parity_report` and `operations.run_log`; direct HTTP wrapper hides exceptions unlike the durable lower-level call. | — |
| `software-classify-only` | `ingest/software_findings.py` / `classify(incremental=True)` | Reads changed installations/catalog/intelligence; updates findings and incremental markers. Returned affected count is not proof of fresh prerequisite revisions. | — |
| `software-classify-full` | same / `classify(incremental=False)` | Tenant-wide findings rebuild from current catalog/intelligence; shares exclusion with both other classifier modes. | — |
| `software-classify` | operator queue / `_software_classify_with_intel` | Optional matcher/Winget/Chocolatey, full classifier, then software-safety materialized view refresh. Underlying nonfatal intel/view results must be separated into required child outcomes. | — |
| `software-enqueue-orgs` | main / `enqueue_all_orgs_once` | Reads Ninja organizations and coalesces Q1 scheduled rows. Queue-disabled/no-org cases return `None`; admission is not inventory completion. | — |
| `software-queue-drain` | main / `run_software_queue_once` | Drains Q3 then Q1 with configured batch size; inventory/current/history/read-model writes. Each item needs its own retained outcome; a successful drain is not proof every item succeeded. | 39.6 |
| `agent-compliance` | main / `run_agent_compliance_once` | Optional legacy bridge, process-local lock, legacy writes; starts an untracked resolver thread after return. Disabled/busy is currently a normal return. | — |
| `agent-compliance-evaluate` | main / `run_agent_compliance_evaluate_once` | Same legacy lock/gate; evaluates with `send_alerts=True`. External alert delivery makes replay review necessary even though its name sounds read-only. | 19.0 |
| `notifications-dispatch` | `ingest/notifications.py` / `dispatch` | Reads rules/findings/freshness/suppressions; sends externally and writes notification state/events. Lower-level send helpers return failed results rather than always raising; response loss is uncertain. | — |
| `notifications-digest` | `ingest/notifications_digest.py` / `send_digest` | Reads routes/findings, sends summaries and writes delivery evidence. Count returned does not certify all routes delivered; no automatic replay after uncertain send. | — |
| `retention-history` | main / `run_observation_history_prune_once` | Purges closed generic/software/claim history through retention functions. Destructive data operation under existing policy; catches exceptions and returns `None`. No new retention policy is approved here. | 0.7 |
| `intel-nvd` | `ingest/intel/nvd.py` / `run_once` | External feed reads; global `intel.cves` writes; optional intel gate and diagnostic `record_run`. Global corpus exclusion is required independently of tenant Jobs. | 58.5 |
| `intel-cpe-dict` | `ingest/intel/cpe_dict.py` / `run_once` | External dictionary reads, `intel.cpes` and backfill-state writes. Retained paging state is not a reviewed Job cancellation/replay boundary. | — |
| `intel-kev` | `ingest/intel/cisa_kev.py` / `run_once` | Global CVE KEV update from external corpus; shared CVE resources with NVD/EPSS. | 2.5 |
| `intel-epss` | `ingest/intel/epss.py` / `run_once` | Global `intel.cves` score update from feed. Count/diagnostic status is not a published material revision. | — |
| `intel-matcher` | `ingest/intel/matcher.py` / `run_once` | Reads software/CVE corpus; replaces tenant `operations.cve_match`; software-safety refresh failure is caught. | 866.7 |
| `intel-winget` | `ingest/intel/winget.py` / `run_once` | Reads external package metadata; writes `operations.safety_signal`; competes with consumers of that intelligence. | — |
| `intel-chocolatey` | `ingest/intel/chocolatey.py` / `run_once` | External package metadata and safety signals; global/package and tenant signal effects must be distinguished. | — |
| `intel-capability` | `ingest/intel/capability_match.py` / `run_once` | Projects `catalog.capability_assertion_machine` from corpus/rules; global catalog writes despite tenant-scoped admission. | — |
| `intel-category` | `ingest/intel/category_match.py` / `run_once` | Projects/withdraws `catalog.category_assertion_machine`; global catalog exclusion and material revision needed. | — |
| `intel-lolrmm` | `ingest/intel/lolrmm.py` / `run_once` | Updates global `catalog.lolrmm_tool` and capability assertions, including withdrawals. | — |
| `intel-otx` | `ingest/intel/otx.py` / `run_once` | External threat feed and tenant safety signals; returned row count and connector status do not link a Job attempt. | 4.3 |
| `intel-abusech` | `ingest/intel/abusech.py` / `run_once` | External malware intelligence and tenant safety signals; same diagnostic/revision limitation. | 95.7 |
| `intel-endoflife` | main / `run_intel_endoflife_once` | Global EOL products/releases, software-version projection, Windows servicing and findings. Fetch/projection failures are swallowed and downstream work still runs against retained corpus. | — |

## Noncatalog execution and control paths

| Path / owner | Trigger, current boundary, and required treatment |
| --- | --- |
| Source demand / `ingest/source_run_queue.py` | `/run/sources`, enqueue/status routes, and Operations callers. Pending-only coalescing, one daemon per request, conditional claim by ID. Ninja uses the smaller observation cycle, not full patch collection; other supported platforms use configured fetchers, resolver, derived refresh, and CMDB evaluator. Preserve platform/source selection and inspect each source result. |
| Software Q2 / main demand closure and `run_software_scoped` | HTTP-scoped software execution uses threads independent of durable Jobs. Inventory writer uses `inventory.software.scoped` or `inventory.software`; Q2 status and per-item exceptions need explicit linked results. |
| Source actions / `ingest/source_actions.py` | Minute cadence drains at most 10 items, five-minute lease, eligibility recheck, external Hudu archive, then evidence/CMDB refresh. The wrapper returns completed/failed/cancelled counts. External action intent and every attempt survive uncertain delivery; no automatic retry. |
| Review digest / main `run_review_digest_once` | Direct HTTP thread, guarded by legacy capability and digest setting; sends external alerts and writes `agent_compliance.review_digest` diagnostics. Not one of the 30 catalog keys. |
| Legacy action evaluation / main `schedule_agent_compliance_evaluate` | Called after a UI action, starts an evaluation thread if capability and readiness permit. This is another admission path, not a schedule. |
| Windows servicing / main `run_windows_servicing_once` | Inline child after Ninja collection or EOL refresh; projections/findings failures are swallowed. Needs its own required/optional child result. |
| Shared projectors / `ingest/derived.py` | Source links, attribute claims, effective attributes, entity candidates, OS installations, relationships, then SQL `refresh_derived()`. Several catches still describe shadow behavior; current readers must determine required children. |
| CMDB evaluation / main and source queue | Inline after documentation/source-action/source-demand refresh; exceptions currently nonfatal. Approved root completion requires visibility when it is a required child. |
| Source stale recovery | 15-minute cadence; processing older than 30 minutes marked failed. Does not stop its thread. |
| Operator queue polling/recovery | One ten-second registration per lane; minute stale recovery, plus startup interrupted recovery. Pollers become worker infrastructure; recovery becomes reserved control work without stealing contained resources. |
| Software stale recovery / inventory queue | Q1/Q3 stale processing reset to pending; Q2 fails. Must not run unchanged against converted rows. |
| Diagnostic reaper / `ingest/runlog.py` | 30-minute cadence and startup cleanup; modifies diagnostic logs, not proof of Job completion or child death. |
| Platform-health findings / main `_run_platform_findings` | 30-minute cadence, exceptions swallowed; reads queues/run diagnostics and writes admin health findings. Keep control capacity independent of inspected jobs. |
| Startup / main | Migration/bootstrap readiness, conditional patch thread, unconditional agent admission, documentation/software overdue admissions, intelligence catch-up, HTTP and Metabase threads. Snapshot retains calls/guards; startup restart must not become a second schedule authority. |
| Metabase bootstrap / main | Startup plus bootstrap HTTP thread; external dashboard mutation. Separate service/maintenance permission and explicit registration before any new Run now exposure. |
| HTTP server and heartbeat threads | Infrastructure, not business Jobs. Preserve liveness reporting without recursively creating a Job for each heartbeat. |

## Diagnostic and consumer reconciliation

`run_log()` calls are not the only producers. Six runtime files insert directly
into `operations.run_log`; the snapshot records their SQL separately. Source
collection builds `source.<platform>.<source_key>` in `_record_source_run`,
truncates to 80 characters, and catches diagnostic-write failure. Do not put
actual source keys into checked-in metadata or pretend those names uniquely
identify invocations. Intel uses `operations.intel_ingest_status` through
`record_run`, not a per-attempt run-log row.

Catalog status keys such as `identity_resolver` and `notifications_dispatch`
are consumer expectations, not automatically verified diagnostic producers.
The earlier inventory wrongly listed these alongside real dynamic producers.
The new catalog and producer categories are deliberately separate.

The current source collector catches failures for each source and returns
successful counts only. A source-demand row can therefore become `done` after
a failed fetch; the new root-completion contract needs a collector adapter
that retains per-source failure/skip outcomes, not just a wrapper that checks
for exceptions. This affects automatic and demand paths equally.

`evidence.consumers` records 17 runtime files with literal queue/run-log/event
references. It includes writers as well as readers. Historical SQL views,
indirect model/function readers, dynamically built SQL, and external consumers
are not certified by that count. Keep old schema/statuses until their relevant
read paths are audited during compatibility implementation.

## Remaining conversion evidence

The source inventory now establishes actual entry points and failure hazards.
It does not choose per-handler deadlines, certify kill safety, establish a
deployment budget, or prove a complete transitive SQL-write graph. Before
enabling a converted family, its adapter review must name:

1. Same-tenant source/client ownership and every effective write scope.
2. Required versus optional child results, including collector partial failure.
3. Material input/output revision producers and freshness checks.
4. Safe cancellation checkpoints and an explicit retry/reconciliation rule.
5. Reviewed external-effect and database interruption behavior.

Unaudited handlers remain ineligible for forced kill and automatic retry under
the approved policy. They cannot be activated merely because the static
inventory passes. No family activation is authorized by this document.
