# Unified Jobs framework

## Status

**Step 2.3 in progress; the resource/fairness policy is approved.** Step 2.2
implementation is complete with a documented local-PostgreSQL validation
limitation. WP0 has a useful
partial inventory and focused source-discovery checks, but its full exit is
not yet proven. ADR-0024's detailed contract and migration companion remain
the design authority; the tenant boundary, root-completion rule, quiesced
cutover direction, and constrained 2.2 activation scope are accepted.
Preserve unrelated untracked root `.work/probe_*` and bootstrap files.

## Goal

Make every scheduled, automatic, operator-requested, and system-maintenance
operation governed by one Jobs framework. It must safely run independent work
in parallel, serialize conflicting work, expose truthful status and progress,
recover from failures and stalled execution, and explain exactly what an
operator can do next.

The framework is not a replacement for source evidence, findings, source
actions, or domain queues. It is the shared control-plane contract for the
execution of work that owns those domains.

## Confirmed baseline

- `operations.operator_job_runs` is a durable queue for many collection,
  evaluation, intelligence, notification, and maintenance jobs. It has lanes,
  stages, heartbeats, retry/cancel controls, and queue-health reporting.
- Software classification already proves the needed pattern: its three modes
  have a dedicated lane and a mode-supersession policy.
- The Jobs catalog and the durable queue were previously disconnected. Release
  `e6bc64b` corrected the catalog to read queue history first and to label the
  disabled Agent compliance bridge accurately.
- `operations.source_run_queue` is a separate source-demand domain queue. It
  immediately starts daemon threads, has independent lifecycle names, and is
  not visible in the common Job activity page.
- `operations.source_action_requests`, source queue recovery, run-log cleanup,
  platform-health evaluation, and the scheduler itself have no common run
  ledger or consistent operator surface.
- APScheduler schedules are in memory. After a restart their cadence starts
  again, and the UI cannot reliably state next due time, skipped cadence,
  dependency wait, or why work is unavailable.
- A fixed two-thread capacity semaphore and in-process execution mean a slow or
  stuck function can still occupy scarce capacity. Marking its row stalled does
  not stop the Python thread.

## Success criteria

1. Every background operation has exactly one registered definition and an
   unambiguous owner, technical key, plain-language name, description,
   eligibility rule, cadence/trigger, lane, resource/concurrency key,
   dependency policy, timeout, retry policy, progress contract, and run result
   contract.
2. Every invocation receives one durable Job run before work starts. This
   includes scheduler work, Jobs-page requests, targeted refreshes, source
   demand, source actions, and internal maintenance work.
3. The Jobs catalog, Job activity, Admin Health, and API read the same durable
   run and schedule state. `run_log` remains diagnostic evidence, not an
   alternative lifecycle authority.
4. A long, failed, or stalled job cannot silently block unrelated lanes. A
   timeout is detected, shown, contained, and tied to a safe recovery path.
5. Dependencies are explicit. A source refresh never races its required
   resolver/evaluator; a dependent run is shown as waiting rather than simply
   absent.
6. Operators see simple terms: **Queued**, **Running**, **Completed**,
   **Needs attention**, **Cancelled**, **Disabled**, or **Waiting for…**. The
   technical key, stage, correlation ID, raw error, and policy details remain
   available to administrators in the run detail.
7. Existing source data, findings, notification behavior, operator decisions,
   URLs, and retained run history survive the transition. No queue migration
   deletes history or invents successful work.

## Non-goals

- Do not merge source observations, source actions, findings, or audit history
  into one table.
- Do not expose raw internal failures or implementation terms as normal
  operator labels.
- Do not promise a percentage unless the producer supplies an honest total and
  completed count.
- Do not automatically retry external mutations, notifications, or a job whose
  handler is not explicitly idempotent.
- Do not retire Agent compliance or legacy parity schemas in this work. Their
  retirement remains a separately approved destructive transition.

## Architectural decisions to record before implementation

Create ADR-0024, **Unified Jobs execution contract**, before the first
migration. It must lock the following decisions.

### One registry, two consumers

Create a declarative registry in `shared/` so both images can import it:

- Django reads only presentation, permissions, eligibility, and request
  metadata.
- Ingest maps an approved executable handler to the same technical key.
- Registry metadata must not import Django or ingest implementation modules.
- A startup validation compares registry keys, handler keys, schedules, Jobs
  catalog entries, and database schedule rows. Any missing/duplicate key makes
  the service not ready and creates an Admin Health condition after recovery.

Each definition contains at least:

`key`, `display_name`, `technical_name`, `description`, `owner`, `kind`,
`lane`, `resource_keys`, `concurrency_scope`, `priority`, `schedule`,
`capability/enablement`, `request_schema`, `idempotency_scope`,
`supersession_policy`, `dependencies`, `timeout`, `retry_policy`,
`progress_contract`, `result_contract`, `permission`, and `handler_version`.

### One execution ledger, linked domain queues

Keep `operations.operator_job_runs` as the physical durable execution ledger
for compatibility; do not rename it during the first framework release. Add
the fields needed for the generic contract and refer to it as **Job run** in
the UI/API.

Source-demand and source-action rows remain their domain records because they
hold source/action-specific payload and audit semantics. Add a one-to-one or
explicit link to the Job run. This preserves source-specific query paths while
giving every execution one lifecycle, event journal, timeout, and activity
entry.

### Durable schedule state

The registry defines intended cadence; a tenant-scoped schedule-state table
persists `enabled`, `last_requested_at`, `next_due_at`, `last_outcome`, and
the configuration/definition revision. The scheduler becomes a lightweight
leader-elected request producer, not the executor. It creates coalesced Job
runs when due and records why a cadence was skipped or deferred.

### Isolated workers and controlled cancellation

Move execution out of the ingest HTTP/scheduler process into dedicated worker
processes using the same ingest image. A worker claims one Job run, launches a
bounded child execution, and records stage/heartbeat/result. The supervisor
can terminate a timed-out child after a documented grace period without
killing the scheduler or another lane.

Queued work can be cancelled. Running work receives a cooperative cancellation
request at declared safe checkpoints. A worker may force-stop only a handler
that is explicitly marked kill-safe; otherwise it becomes **Needs attention**
after timeout and its resource key remains protected until recovery is
verified. No current handler is presumed kill-safe without review.

### Resources, lanes, dependencies, and supersession

Lanes are capacity and operator-explanation boundaries, not a substitute for
locking. Every Job definition declares resource keys (for example
`db-write`, `ninja-api`, `source:<platform>`, `software-classifier`, or
`notifications`) and a concurrency scope (tenant, client, source, or fleet).
The claim query atomically respects both the lane capacity and held resource
keys.

Dependencies use durable prerequisite requests and material revisions, not
untracked threads. A dependent Job run is queued with a visible reason until
its prerequisite succeeds with the needed freshness/revision. Supersession is
declared per family: a broader run may cancel queued narrower work; it never
silently stops running work.

## Complete inventory and target treatment

| Family | Registered work | Target treatment |
| --- | --- | --- |
| Collection | `patches`, `agent-observations`, `documentation-observations`, source-demand Ninja/SentinelOne/ScreenConnect/LogMeIn/Hudu and future enabled sources | One collection contract per source scope. Source-demand payload remains in `source_run_queue`, linked to its Job run. Serialize the same source/client scope; allow independent sources within proven API/DB capacity. |
| Identity and evaluation | `resolver`, `platform-evaluate`, `patch-classify`, `parity-check` | Explicit dependency/freshness inputs. Resolver and evaluators become separately observable work; no evaluator bypasses the ledger. |
| Software | `software-enqueue-orgs`, `software-queue-drain`, `software-classify-only`, `software-classify-full`, `software-classify` | Retain the current dedicated Software lane and incremental/full/auto-intel supersession. Link inventory batches to the classifier revision they make eligible. |
| Intelligence | `intel-nvd`, `intel-cpe-dict`, `intel-kev`, `intel-epss`, `intel-matcher`, `intel-winget`, `intel-chocolatey`, `intel-capability`, `intel-lolrmm`, `intel-otx`, `intel-abusech`, `intel-endoflife`, `intel-category` | Use bounded intelligence/API resources. Material-change output requests a coalesced dependent full software classification only when its defined inputs changed. |
| Notifications | `notifications-dispatch`, `notifications-digest` | Idempotent dispatch/digest stages with delivery audit links. Retry policy is explicit and never duplicates externally delivered messages. |
| Retention and health | `retention-history`, source queue stale recovery, Jobs stale recovery, run-log stale recovery, platform-health findings | Register as internal maintenance jobs. Show them in Admin Job activity and Health, but do not offer normal operator Run now unless the handler is explicitly safe. |
| Source actions | `source_actions.process_pending` plus individual external source actions | Retain `source_action_requests`; create linked Job runs for processing attempts. Per-action idempotency, retryability, and external correlation are mandatory. |
| Legacy bridge | `agent-compliance`, `agent-compliance-evaluate`, review digest | Register only as an optional legacy capability. When disabled, show Disabled and do not enqueue periodic no-op work. When enabled, run through the same framework and replace its internal resolver thread with a durable dependency. |
| Service/bootstrap | scheduler leader, migration/bootstrap, Metabase bootstrap, HTTP server | Surface health and startup events separately from normal work. Migration/bootstrap is never an operator Run now job. Metabase bootstrap must be explicitly registered as maintenance before it is exposed. |

## Dependency contract

The registry must declare and test this initial graph:

```text
Source collection
  -> client/identity resolution when the source supplies identity signals
  -> required derived refresh/projector
  -> Platform evaluator or CMDB evaluator for the affected scope

Ninja patch collection -> Patch classifier -> Platform evaluator
Software inventory batch -> incremental Software classifier
Intel material change -> coalesced full Software classifier
Identity resolver -> Platform evaluator (affected scope)
Platform evaluator -> notification dispatch remains cadence-driven
Parity check, retention, and health -> independent; never block collection
Agent compliance (only if enabled) -> Identity resolver -> its native successor
```

Each edge must name its freshness input, affected scope, coalescing key, and
failure behavior. A failed prerequisite blocks the dependent run with a plain
reason; it must not run against partial or stale data merely to make a card
look current.

## Data model and migration sequence

All migrations require separate review and explicit production approval.

1. **Registry and schedule state.** Add `operations.job_schedules` and a
   registry-version table or immutable snapshot fields. Store definition key,
   tenant, enabled/capability result, cadence, requested/next-due times, and
   last request/outcome references. Add RLS, ownership, grants, indexes, and
   queue-registry health coverage.
2. **Generic Job-run contract.** Extend `operator_job_runs` with immutable
   definition revision, trigger (`automatic`, `operator`, `dependency`,
   `recovery`), request payload, idempotency key, correlation ID, parent/root
   run IDs, dependency state/reason, cancellation request fields, timeout,
   started/finished resource metadata, structured sanitized result, and
   terminal reason. Backfill only factual defaults for existing rows.
3. **Resource claims and event journal.** Add a tenant-scoped resource-claim
   table and append-only Job event records for requested, deferred, claimed,
   stage, checkpoint, cancellation, retry, timeout, finish, and recovery.
   Enforce append-only writes through role grants/trigger policy; retain the
   current event table only if it can meet that contract.
4. **Domain queue links.** Add nullable Job-run foreign keys to source-demand
   and source-action records. Backfill no fictional links. New work must write
   both records atomically before execution.
5. **Compatibility views/API.** Preserve current Jobs URLs and existing
   status readers during migration. Add stable admin views rather than making
   downstream consumers query mutable table details. Do not delete `run_log`.
6. **Cutover and cleanup.** Remove direct daemon-thread entry points only after
   every registered path and regression test uses the framework. Retire
   obsolete indexes/columns in a later, separately reviewed migration.

## Implementation work packages

## Exact execution order and model selection

Run these steps in order. The assigned agent continues automatically to the
next step after a passing validation. It pauses only at an item marked
**Approval gate**, a genuine design contradiction, a failed safety invariant,
or a validation failure it cannot resolve. Do not substitute a lower-tier
model for a step marked Astra.

| Step | Work | Model and reasoning | Required exit before continuing |
| --- | --- | --- | --- |
| 0.1 | Verify the current branch, plan, Docker packaging, untracked-user-work boundary, and all existing Job/queue tests. | **Luna Medium** | Confirmed baseline and no overwritten user work. |
| 0.2 | Generate the complete machine-checked inventory of scheduler entries, `/run/*` routes, direct threads, queues, handlers, catalog rows, run-log kinds, and consumers. | **Luna Medium** | Inventory is complete; registry-completeness test fails for an intentionally omitted fixture. |
| 0.3 | Run the approved read-only production measurements and summarize durations, depth, duplicate requests, timeouts, deadlocks, and run-log-only history. | **Luna Medium** | Redacted measurement artifact and documented capacity assumptions. |
| 1.1 | Reconcile inventory/measurements with the proposed architecture; decide the exact registry contract, Job-run extensions, schedule-state schema, resource claims, worker isolation, cancellation model, and compatibility path. Write ADR-0024. | **Astra High** | ADR-0024 and migration design are internally consistent and reviewed against RLS, source queues, source actions, and all consumers. |
| 1.2 | Review ADR-0024, the proposed SQL migrations, destructive/compatibility implications, Compose worker topology, and rollback plan. | **Astra High** | **Approval gate:** user explicitly approves the architecture and reviewed migrations before any schema or worker-service change. |
| 2.1 | Implement the shared declarative registry, Django/ingest registry validation, capability model, technical/operator labels, and registry completeness tests. | **Sol High** | Both services load the same definitions; missing, duplicate, or unhandled keys fail readiness/tests. |
| 2.2 | Implement additive schedule-state and generic Job-run migrations, RLS/grants, request/coalescing API, schedule leader election, and migration tests. | **Astra High** | Concurrent request/schedule tests prove idempotency, restart safety, tenant isolation, and no raw-row caller remains. |
| 2.2a | Close the missing Step 2.3 policy inputs: initial deployment/lane capacities, Job resource mapping, priority aging, dependency activation boundary, and supersession policy. | **Astra High** | **Approval gate:** user explicitly approves `jobs-resource-policy-review.md`; no enforcement uses proposed values before approval. |
| 2.3 | Implement atomic resource claims, lane capacity, priority aging, dependency wait/release, and declarative supersession. | **Astra High** | Deadlock, contention, dependency, and Software-mode regression tests pass. |
| 3.1 | Add the worker service/entry point, child-process supervisor, health checks, packaging, and local integration fixture. | **Astra High** | Scheduler/HTTP remain responsive while a test job is running; Compose and Docker review pass. |
| 3.2 | Implement factual progress, checkpoints, cooperative cancellation, timeout/grace, safe kill eligibility, orphan recovery, and retry rules. | **Astra High** | Hang, restart, cancellation, and no-double-execution tests pass without falsely completing a run. |
| 4.1 | Migrate existing durable evaluation, Software, intelligence, notification, and retention handlers to the registry without changing their business results. | **Sol High** | Per-family compatibility and run-history tests pass. |
| 4.2 | Migrate source-demand work from direct daemon threads to linked source Job runs, retaining source queue records and scoped forms. | **Sol High** | Every on-demand source run has linked domain/Job records and no direct execution thread. |
| 4.3 | Link source-action attempts and internal maintenance work to Job runs; apply explicit idempotency and retry contracts. | **Sol High** | Source-action and maintenance failure/retry tests pass. |
| 4.4 | Capability-gate the legacy bridge and replace its resolver thread with a durable dependency when enabled. | **Sol High** | Disabled bridge creates no schedule/run noise; enabled bridge follows the declared dependency graph. |
| 5.1 | Implement and validate the full dependency graph, scope/revision freshness checks, and evaluator/notification recovery safety. | **Astra High** | Failure-injection suite proves no partial data evaluation, premature recovery, or duplicate notification/action. |
| 6.1 | Build the unified Jobs home, activity filters, detail/timeline, plain-language status, safe actions, admin diagnostics, and source/health links. | **Sol High** | Request/UI/permission tests prove every status and link uses the authoritative Job run. |
| 6.2 | Apply visual polish, copy review, accessibility checks, and documentation/runbook updates. | **Luna Medium** | Operator wording is consistent and no internal diagnostics leak to ordinary operators. |
| 7.1 | Run full repository validation, migration/order review, deployment-readiness audit, and a focused code/design review. | **Astra High** | **Approval gate:** user approves commit, push, deployment, and the exact reviewed migrations. |
| 7.2 | After approved rollout, run read-only production reconciliation, health checks, query-plan review, and operator smoke tests. | **Sol High** | Results are recorded; unresolved rollout defects return to their owning step. |
| 7.3 | Review the observation period and approve removal of direct-thread/status compatibility paths, if warranted. | **Astra High** | **Approval gate:** no cleanup or legacy retirement occurs without separate explicit authorization. |

The practical cost-saving rule is simple: Luna does bounded discovery, test,
documentation, and presentation work; Sol implements well-specified code;
Astra owns architecture, migrations, concurrency, worker lifecycle, failure
safety, and final review.

### WP0 — Freeze the catalog and baseline

- Generate a checked-in registry inventory from every APScheduler entry,
  `/run/*` endpoint, direct thread start, queue processor, targeted refresh,
  and startup catch-up.
- For each entry record current handler, owner, source/action tables, run-log
  kind, cadence, current concurrency, maximum observed duration, safe retry,
  cancellation checkpoint, prerequisites, output, and consumer surface.
- Run read-only production measurements for queue depth, duration percentiles,
  duplicate requests, stale runs, deadlocks, source demand, and run-log-only
  activity. Redact customer data from the artifact.
- Add a registry completeness test that fails for any unregistered scheduled
  or HTTP-triggered background handler.

Exit: a reviewed inventory with no unknown background execution path.

### WP1 — ADR, registry, and capability model

- Create ADR-0024 and `shared` registry definitions.
- Define user-facing labels plus short descriptions; retain technical keys in
  admin detail instead of replacing them with vague names.
- Define permissions: ordinary operators request only scoped, safe work;
  administrators request fleet work, retry, cancel queued work, and see raw
  diagnostics; system work has no Run now control unless specifically allowed.
- Define capability checks for disabled source instances, notification flags,
  intel, and legacy Agent compliance. Disabled means not schedulable and has a
  stated reason, not "Never run."

Exit: Django and ingest load one validated definition set without importing one
another's runtime code.

### WP2 — Durable request, schedule, and resource foundations

- Implement reviewed migrations 1–3 above.
- Build transaction-safe request/coalescing APIs used by Django, scheduler,
  dependency triggers, and recovery. Do not let any caller insert raw rows.
- Implement persistent schedule reconciliation with a PostgreSQL advisory-lock
  scheduler leader. It must calculate next due time deterministically across
  restarts, coalesce missed ticks, and never enqueue work solely because a
  container restarted.
- Implement atomic lane/resource claim and release, priority aging, dependency
  waits, and explicit queue position within the relevant lane/resource scope.

Exit: synthetic jobs prove no duplicate claim, no cross-lane starvation, and
correct restart/cadence behavior.

### WP3 — Worker isolation, progress, timeout, and recovery

- Add a dedicated worker entry point/service in Compose using the ingest image;
  verify Docker packaging and health checks.
- Move execution from scheduler threads to the worker supervisor and bounded
  child process model. The scheduler and HTTP server must remain responsive
  during a long job.
- Add progress/checkpoint helpers that record only real stage and count data.
- Implement cancellation request, cooperative checkpoints, timeout/grace,
  terminal **Needs attention**, resource containment, retry eligibility, and
  manual recovery controls.
- Add a startup/restart reconciliation routine that distinguishes an orphaned
  child from a still-live worker before marking a run terminal.

Exit: intentionally hung test handlers do not prevent unrelated collection or
evaluation from progressing, and no false completed state is possible.

### WP4 — Migrate work families in safe dependency order

1. Migrate current `operator_job_runs` families (evaluation, Software,
   intelligence, notification, retention) onto the registry without changing
   their business behavior.
2. Move source demand from daemon threads to linked source Job runs. Preserve
   source queue records, source-specific payload, scoped selector forms, and
   source health semantics.
3. Link source action processing and enforce per-action retry/idempotency.
4. Move internal cleanup/health work to registered maintenance runs.
5. Replace legacy HTTP `/run/*` execution with request creation or a redirect
   to the correct scoped form. Keep compatibility endpoints only while callers
   are audited; they must never create an untracked thread.
6. Gate the Agent compliance bridge by capability. If enabled, migrate its
   resolver follow-up into an explicit dependency; if disabled, do not schedule
   it.

Exit: the completeness test proves every known work family starts through the
framework and all prior direct thread routes are removed or intentionally
disabled.

### WP5 — Dependencies, supersession, and correctness rules

- Implement the dependency graph above using revision/scope evidence, not a
  blanket "run everything" chain.
- Generalize Software mode supersession into declarative per-family policies.
- Define collection and source concurrency by source/client scope and verify
  API rate limits, DB-write load, and resolver/evaluator consistency.
- Make evaluator outcomes safe under retries: no premature recovery, duplicate
  notifications, source action duplication, or loss of operator decisions.
- Add failure injection for deadlocks, database pool exhaustion, source API
  timeout, worker restart, partial source collection, and dependency failure.

Exit: each registered dependency and supersession rule has a direct regression
test and an operator-visible waiting explanation.

### WP6 — Operator and administrator surfaces

- Replace the split Jobs catalog/Job activity status model with one Jobs home:
  compact category summary, registered work list, capability/schedule state,
  and a link to filtered activity.
- Job activity supports all jobs, source/client scope, lane, origin, status,
  owner, correlation/batch, time range, and technical key filters. It includes
  current and historical work without a silent record cap.
- Detail view shows plain status, start/end/elapsed, wait reason, honest
  progress, scope, result, next action, event timeline, safe Retry/Cancel, and
  administrator-only diagnostics/error/correlation data.
- Provide direct links from source health, targeted refresh, source-action
  pages, Admin Health, findings/evaluators, and affected client/device pages to
  the relevant Job run or filtered activity.
- Admin Health emits deduplicated, actionable findings for schedule failure,
  disabled-required work, queue age/depth, repeated failure, timeout, registry
  mismatch, and unmet dependency. Each finding links to its Job detail.

Exit: an operator can answer what is running, what is waiting, why, what it
affects, and what they can safely do in one place.

### WP7 — Cutover, performance, and retirement review

- Run read-only production query-plan/duration review for activity and health
  queries; add only measured indexes/partitioning/retention policy.
- Verify all containers, migrations, scheduler leader, worker health, queue
  health, registry validation, catalog/API behavior, and each job family after
  rollout.
- Run a dual-read reconciliation while old status paths remain: durable Job
  runs versus source queue/run-log evidence must be explained, not silently
  overwritten.
- Remove obsolete direct threads and duplicate status readers only after an
  approved production observation period. Treat Agent compliance retirement as
  a separate destructive project.

Exit: one authoritative execution lifecycle with documented compatibility and
no untracked background work.

## Required tests and validation

- Registry completeness and handler/catalog/schedule parity.
- Tenant/RLS/grant tests for every new table/view and role.
- Request idempotency, concurrent coalescing, lane/resource claim, priority
  aging, dependency wait/release, and supersession tests.
- Scheduler-leader, restart, missed cadence, disabled capability, and next-due
  tests.
- Worker heartbeat, timeout, cooperative cancel, forced-stop eligibility,
  orphan recovery, retry safety, and no-double-execution tests.
- Per-family integration tests for collection, source demand, resolver,
  evaluator, Software, intel, notification, source action, retention, and the
  disabled/enabled legacy bridge.
- UI/API/CSV smoke tests for labels, filters, detail visibility, diagnostics
  permissions, and links.
- Python compilation/import tests, targeted Ruff, Django checks,
  `makemigrations --check`, migration drift/order review, `git diff --check`,
  Compose/Dockerfile review, and full relevant ingest/Operations suites.
- Before production: backup/review of migrations; after production: read-only
  health, queue, schedule, job-family, and query-plan verification.

## Risks and safeguards

| Risk | Safeguard |
| --- | --- |
| Killing a process leaves partial external or database work | Only terminate reviewed kill-safe handlers; all others require cooperative checkpoints and manual recovery. |
| Duplicate work after restart or scheduler race | Durable idempotency keys, advisory leader lock, resource claims, and unique active scopes. |
| One slow job blocks all work | Independent lane workers plus resource-specific limits; use measured capacity rather than global thread count. |
| UI says success without evidence | Completion is written only by the worker after the handler returns a declared result; direct `run_log` is evidence, never lifecycle authority. |
| Source-specific semantics are lost | Keep source/action queues as domain tables and link them to Job runs instead of flattening payloads. |
| Legacy bridge creates no-op noise | Capability-gate it; disabled work does not schedule or expose a run button. |
| Large migration breaks deployed queue | Additive migrations, compatibility readers, factual-only backfills, dual-read observation, and later cleanup. |

## Files expected to change

- New shared registry/contract module and tests under `shared/`.
- `ingest/main.py`, a new scheduler/worker entry point, queue dispatcher,
  source-demand and source-action adapters, config, and ingest tests.
- `operations/apps/core/views.py`, models/migrations, Jobs/Admin Health APIs,
  templates, URLs, permissions, and Operations tests.
- `docker-compose.yml`, ingest Docker entry point/packaging, and operational
  documentation/runbooks.
- `operations/docs/decisions/0024-...`, `operations/docs/architecture.md`,
  `operations/docs/runbooks/`, root `VERSION`, and `CHANGELOG.md` when a
  reviewed implementation release is prepared.

## Handoff instructions

Work packages are sequential gates. The implementation agent must continue to
the next approved work package without pausing after routine edits, tests, or
documentation updates. Pause only for a genuine product decision, a reviewed
migration/production approval boundary, a safety conflict, or a failed
validation that cannot be resolved within the package. Keep this plan current
with confirmed decisions, completed package exits, validation, and the next
action; do not turn it into a transcript.

## Current checkpoint and next action

Repository baseline `e6bc64b`, branch `master`. The plan is modified. Task
artifacts under `shared/`, Operations tests, Operations `.work/`, and the two
ADR-0024 documents remain untracked, not checked in. Unrelated root
`.work/probe_*` and bootstrap files remain untouched. No runtime code,
schema, Compose, or deployment changes occurred in the drafting phase.

The machine-checked inventory is now schema version 2. It scans executable
Python under `ingest/` and `operations/apps/`, excluding tests, migrations,
comments, and docstrings. It records 33 scheduler registrations, 49 route
literals, 34 direct threads, 30 catalog/dispatcher keys, 16 `run_log` calls,
seven qualified queue relations, 17 relation consumers, six direct run-log
writers, startup calls, and follow-up/admission calls. Four focused tests pass,
including independent synthetic source additions and category omission checks.
It still cannot prove configuration-dependent dispatch, transitive SQL writes,
external callers, handler retry/kill safety, or runtime result correctness.
`jobs-handler-audit.md` records those explicit unknowns and the found
partial-success/wrapper hazards. The measurement artifact remains partial as
previously recorded. Source queues lack tenant columns; source-action migration
0160 has a tenant column but no RLS. DESIGN section 5's automatic stale
reset/retry conflicts with the proposed execution containment policy.

Prepared `operations/docs/decisions/0024-unified-jobs-execution-contract.md`
and `0024-unified-jobs-migration-design.md`. They define proposed request and
coalescing identities, snapshots, durable schedules, dependency revisions,
resource containment, worker fencing, domain attempt links, RLS/grants,
read compatibility, cutover, and rollback requirements. DESIGN section 5's
retry/reset policy is explicitly called out for proposed supersession.

Prepared `operations/.work/jobs-schema-preparation.sql` and its review note.
This is exact, rollback-terminated, inert M1/M2 preparation SQL outside the
migration graph: it adds no runtime grants, enables no schedules, and rejects
all nonlegacy contract versions. It covers immutable definition snapshots,
same-tenant request/schedule/tick references, tenant-1 RLS for new tenant
tables, and factual-only preflight checks. It does not provide the later
resource/dependency/domain-link/transition/worker migration set, role audit,
or activation; it has not been executed.

Prepared `operations/.work/jobs-topology-review.md`. The current ingest image
already packages `shared/` and all of `ingest/`, so a future worker module can
use the same image. The current `ingest.main` command cannot be copied as a
worker because it also starts HTTP, schedules, migrations, catch-up, and
bootstrap. A future worker must override its command and inherited HTTP
healthcheck. No replica/capacity/connection numbers were selected.

Added `operations/.work/jobs-measure.sql`: aggregate-only, repeatable-read,
read-only, statement/lock timeouts, stop-on-error, and rollback. Its interrupted
invocation returned initial status and zero active duplicate groups only.
The local tool session is unavailable; remote completion was not verified.
No new complete measurement result is claimed. The report corrects omitted
NVD/OTX/KEV/retention samples and identifies remaining evidence limitations.

Validation is intentionally light per the user's request: source review
against ADR-0012, glossary, DESIGN, queue migrations, current handlers,
Dockerfiles, and entrypoints, plus document-reference and whitespace checks.
No broad test suite, migration execution, or worker exercise was performed.
Focused validation: `pytest apps/core/tests/test_jobs_inventory.py -q` (4
passed), Ruff check/format of that test, Python compile of it, schema-draft
inert/RLS/preparation-constraint static guards, and `git diff --check`.
The inventory checks do not prove tenant isolation or failure recovery. The
earlier missing-`apscheduler` test limitation remains.

The user approved retaining tenant-1 execution initially, requiring
workflow-root completion after required children, and a quiesced cutover with
uncertain work reconciled manually. These are design choices, not migration
or deployment approval. The user approved the step 1.2 architecture and the
reviewed inert M1/M2 migration scope on 2026-09-24. That approval covers the
ADR/migration design, handler audit, preparation SQL/review note, and worker
topology review. It does not authorize executing a migration, enabling a
schedule, adding workers, changing Compose, deployment, or choosing capacities.
Resource/dependency/domain-link enforcement remains specified but intentionally
deferred to later additive migrations. Step 2.1 is complete: added
`shared/jobs_registry.py`, a standard-library-only registry of all 30 current
durable operator-queue definitions and their current catalog/lane/capability/
schedule metadata. Operations builds its static catalog and lane lookup from
the registry; ingest uses it for lane lookup and validates independent handler
and scheduled-key sets before readiness. Capability labels retain the legacy
bridge wording and expose the same disabled state for Intel, notifications,
and software-queue definitions. Resource keys remain empty and retry/kill
metadata explicitly says unreviewed; no metadata is treated as enforcement.

`test_jobs_registry.py` proves registry/catalog/handler/scheduler parity and
rejection of missing, duplicate, and unregistered keys. The machine inventory
continues to verify source-derived catalog/handler coverage after the catalog
moved to `shared/`. Focused validation passed: Python compile; Ruff for the
new/shared tests and registry; import-order review of `views.py`; and
`pytest apps/core/tests/test_jobs_inventory.py apps/core/tests/test_jobs_registry.py
apps/core/tests/test_operator_jobs.py -q` (12 passed). Full Ruff remains out
of scope and reports pre-existing diagnostics in the large views/main/queue
modules; no broad suite was run. `git diff --check` passed.

Step 2.2 began on Astra High. Added Operations migration 0183,
`jobs_contract_preparation`, implementing the approved inert M1/M2 storage:
immutable global definition snapshots; nullable generic Job-run fields and
same-tenant references; request, schedule, and schedule-event tables; forced
tenant-1 RLS; no runtime table/function grants; and checks that permit only
legacy contract version 0 and disabled schedules. It is intentionally
irreversible rather than dropping potential retained ledger history. Added
focused static migration checks. Python compilation and the Jobs focused suite
passed (14 tests); Docker Compose configuration parses with only its existing
obsolete-`version` warning. Local `psql` is unavailable, so no PostgreSQL DDL
or migration execution was performed. No database, deployment, worker, or
Compose state changed.

The user then approved the narrow follow-on activation scope: version-1 Job
admission, enabled schedule state, and explicit `EXECUTE` grants only for
constrained request/coalescing and scheduler-leader APIs. Added Operations
migration 0184, `jobs_admission_and_schedule_apis`. It replaces only the two
preparation guards, adds immutable definition registration, tenant-context
checked request/admission, schedule leader acquire/release, and due-schedule
claim APIs, and grants no direct table access. The request API rejects missing
snapshots, cross-tenant actors, malformed/null inputs, and top-level sensitive
payload keys; it preserves the legacy active-row compatibility fence and
requires conflicting legacy or differently scoped active work to drain.
Schedule claims lock their schedule row and record a single configuration/due
tick event. No schedule rows were seeded or enabled, no definition snapshots
were registered, and no caller was switched to these APIs. Existing version-0
writers remain unchanged for compatibility pending their family migrations;
the current cross-key Software supersession writer cannot be replaced until
the Step 2.3 declarative supersession API exists.

Focused static validation now passes: Python compilation, targeted Ruff
(`E`, `F`, `I`) for migrations/tests, and 17 Jobs migration/registry/queue
tests. `git diff --check` passes (with only existing LF-to-CRLF warnings).
Local `psql` remains unavailable, so neither migration nor a synthetic
PostgreSQL concurrency/RLS test was run. No database, deployment, worker, or
Compose state changed. The user directed that existing version-0 writers stay
through Step 2.3 rather than adding an interim cross-key supersession policy.
Accordingly, the Step 2.2 raw-writer exit means no direct table write may
create a converted version-1 Job; legacy version-0 writers are explicit
compatibility paths, not converted Jobs. Step 2.3 owns their replacement by
the reviewed declarative supersession API.

The Step 2.3 inspection found a plan gap: Step 1.1/1.2 did not close numeric
capacity, resource mapping, priority-aging, or production dependency policy.
The measurements remained partial, `resource_keys` were intentionally empty,
and the topology review explicitly selected no process/connection budget.
Added Step 2.2a and `operations/.work/jobs-resource-policy-review.md` as a
separate approval package. It proposes the evidence-preserving initial ceiling
of two total executions and one per lane, broad tenant-state exclusion, known
global Intel/software-catalog resources, five-minute priority aging capped at
100, generic dependency machinery with no production edges before Step 5.1,
and only the existing Software classifier supersession ordering. These are
proposals, not accepted decisions or active registry values. The user approved
the complete Step 2.2a package on 2026-09-24. Its initial limits, resource
mapping, priority aging, generic-only dependency boundary, and Software-only
supersession policy are now approved Step 2.3 inputs. Current next action:
implement additive enforcement schema and constrained APIs; do not convert
existing version-0 producers or execute any migration.

Step 2.3 implementation has started with migration 0185,
`jobs_claims_and_dependencies`. It adds tenant-scoped lane limits, claim and
dependency storage, policy-revision values, RLS and revokes, and restricted
ingest-only v1 claim/release/dependency APIs. Claims lock every required
resource in sorted identity order, preserve the approved two-slot deployment
limit and one-per-lane limit, use the approved five-minute aging formula, and
create no partial claim when capacity is unavailable. Dependencies reject
cross-version/cycle input, block claim until released, and require a completed
prerequisite to publish the exact output revision. The shared registry now
records the approved resource templates, initial limits, and Software ranks,
but no legacy producer consumes them.

Focused validation passed: Python compilation; targeted Ruff (`E`, `F`, `I`)
for the registry, 0185, and their tests; and 21 focused Jobs migration,
registry, inventory, and queue tests. `git diff --check` passes with only the
existing LF-to-CRLF warnings. Local PostgreSQL remains unavailable, so these
SQL functions have not been executed and concurrency/RLS behavior is not
proven. Current next action: add the converted Software admission API that
uses the approved ranks atomically; retain existing version-0 admission until
the later family conversion.

Recovery checkpoint (2026-09-24): the production Operations container crash-looped
after `6b1ef1f` when migration 0185 attempted to call PostgreSQL `digest()` while
seeding the fixed Jobs resource-policy SHA-256. The production database does not
provide that function. Recovery scope is limited to replacing the runtime hash
calculation with the identical precomputed digest
`6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275`, adding a
static guard, validating the migration, and issuing an approved recovery push.

Findings correction (2026-09-24): active policy `conditions-taxonomy-6` exposes
Client name differences, but its 49 live records are `AdminFinding` rows while
the Issues queue reads only entity `Finding` rows. The approved scope is to
render Admin-owned findings in the same policy taxonomy and selected-type
Issues result, preserve their distinct ownership/actions, and include their
counts in navigation. Do not convert or duplicate evidence between tables.

Client mapping overhaul (2026-09-24): approved to replace fragmented legacy
client-name handling with a native, single-authority mapping decision model.
Scope: mapping provenance and audit, effective source-to-client mapping read
model, source-to-source comparison evidence, evaluator outcomes for explicit,
automatic, unmapped, ambiguous, split/merged, placeholder, and withdrawn
groups, Admin → Integrations → Client mappings, client reference display, and
findings only for review-required states. Do not add a second authority beside
the current source-link relationship or silently infer split/merge mappings.
Current checkpoint: deployed `14135f5` exposes Admin findings in Issues but
its client-name row lacks source-to-source comparison; local uncommitted row
formatting work must be replaced, not committed. Next action: document the
mapping-state contract/ADR and audit current source-link and legacy alias
provenance before additive schema work.

Mapping decision surface checkpoint (2026-09-25): additive migration 0201,
effective mapping view, Operations Integrations → Client mappings route, and
audited decision action are implemented locally. The action uses a restricted
security-definer database function so the Operations role cannot write the
decision table directly; each decision supersedes the prior current record.
The table now exposes explicit, automatic, ignored, and review states with
  reason/provenance. Source-observation evidence is included in the effective
  view and consumed by both the mappings surface and client references.
  Focused queue/workspace tests, template loading, Django checks, migration
  consistency, and Python compilation pass. Local PostgreSQL is unavailable,
  so migration SQL/RLS/function execution remains unverified. Next action:
  review the migration diff and request approval for one logical commit; do
  not push or deploy without separate approval.

Completion pass (2026-09-25): the prior commit delivered the decision surface
but did not complete every approved evaluator path. Active scope is limited to
the missing legacy-alias bridge and evaluator lifecycle: preserve explicit
manual/seed/alignment aliases as explicit per-source decisions, preserve
source-tier aliases as automatic, clear review findings for intentional
placeholder/excluded/withdrawn evidence, and detect incompatible source-name
topology without changing source links. The evaluator must remain evidence-
driven and may not manufacture split/merge mappings. A new policy taxonomy
version will expose any new review type in the general Issues queue. Validation
will cover migration consistency, resolver tests, and Django checks; local
PostgreSQL execution remains a stated limitation.

Completion checkpoint (2026-09-25): migration 0202 imports enabled legacy
aliases into the decision authority without overriding an existing decision;
manual/seed/alignment aliases become explicit and source-tier aliases become
automatic. The resolver now clears stale name-difference findings when active
evidence is withdrawn or marked placeholder, clears excluded/unmapped reviews,
and emits visible split/duplicate-source-group reviews without altering source
links. Policy taxonomy version 7 exposes the new duplicate-source-group type
under Client source mapping. Django checks, migration consistency, Python
compilation, and 118 focused Conditions/Findings/Workspace tests pass. Local
PostgreSQL is unavailable, so migration SQL, alias backfill, RLS, and evaluator
queries remain unexecuted. Next action: review and request separate approval
for the logical completion commit; do not push or deploy without approval.

Production recovery checkpoint (2026-09-25): automatic deployment of
`adecf55` applied 0201 but Operations crash-looped while 0202 tried to read
the `security_invoker` client-link view as `operations_migrate`, which has no
grant on that view. The migration transaction rolled back. The corrective
migration revision now performs the alias bridge through the owned base
relations and the latest active org observation, preserving the same scoped
join and decision semantics. Next action: validate, commit/push the correction,
then verify the automatic redeploy, migrations, health, and active policy.

Second recovery checkpoint (2026-09-25): the corrected alias bridge executed,
but 0202 then failed to seed its new admin finding type because the production
registry requires non-null `subject_scope`. The row is now seeded with the
existing required registry value (`device`) and explicitly disabled device
exposure; admin findings do not bind device subjects. The migration transaction
rolled back, so the revised 0202 remains safe to retry. Next action: validate,
push the corrective commit, and verify startup/migration completion.

Third recovery checkpoint (2026-09-25): the finding-type seed then exposed a
second production non-null registry column, `suppressed_by_approval`. The new
admin-only mapping finding now explicitly sets it false, alongside the already
explicit non-device exposure setting. The migration transaction again rolled
back, so no partial type, policy, or decision data was retained. Next action:
validate and push this final registry-contract correction, then verify health.

Migration 0186, `jobs_software_supersession`, completes the declared
Software-only cross-key admission path for converted v1 Jobs. During its
implementation, the existing request-to-run composite FK was found to require
the request and resolved run to share a definition/digest/scope, contradicting
the approved broader-Software alias behavior. 0186 replaces only that FK with
a same-tenant run reference; request rows retain their own immutable requested
definition, digest, scope, input, and identity. Its restricted API validates
the definition snapshot's declared Software family/rank, serializes the family
with an advisory lock, aliases an equal-or-broader active run, cancels only
queued narrower v1 runs with durable events, and never stops running work. It
then delegates ordinary new-run admission to the constrained 0184 API. The
registry now records `software-classifier` family metadata for the three
approved modes. No existing version-0 writer invokes this API.

Focused validation now passes: Python compilation, targeted Ruff (`E`, `F`,
`I`) for touched registry/migrations/tests, and 23 focused Jobs migration,
registry, inventory, and queue tests. `git diff --check` passes with existing
LF-to-CRLF warnings only. Local PostgreSQL is still unavailable, so 0185/0186
SQL has not run and their lock, RLS, FK-discovery, and concurrency behavior is
not locally proven. Current next action: run the required small synthetic
PostgreSQL claim/contention/dependency/supersession checks when a local test
database is available; do not proceed to worker topology or convert a family
until that Step 2.3 safety validation is evidenced.
