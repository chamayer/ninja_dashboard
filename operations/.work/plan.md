# Admin navigation consistency

## Status

Complete — one operator-facing Admin sub-navigation now renders on every
Admin page, with no page-local duplicate strip.

## Goal and scope

The global Admin context bar in `templates/base.html` is the single navigation
authority. It must expose the same meaningful destinations on Overview,
Sources, mappings, reviews, Jobs, Health, and configuration pages. Remove the
older group-specific `_admin_tabs.html` includes that duplicate or contradict
the global bar. Preserve all URLs and page behavior.

## Validation

- Template compilation and focused navigation tests.
- Confirm all Admin views already provide `admin_group` / `admin_tab` context.

## Validation

`PYTHONPATH=.. python manage.py check` passed. Focused navigation coverage
tests passed: `apps/core/tests/test_coverage.py` (14 passed). `git diff
--check` passed.

---

# Client mapping identity rebuild

## Status

Complete — production data rebuild executed and validated on 2026-09-29.

## Goal

Remove every live source-group-to-client attachment produced by the legacy
compatibility projection, rerun the native resolver, reuse retained legacy
PowerShell aliases as explainable name mappings, and leave every unresolved or
ambiguous source group visible as a candidate and finding.

## Scope and decisions

- Live client-class source links and their observation-derived attachments;
  canonical clients, devices, raw/current evidence, aliases, audit records,
  and historical link evidence remain intact.
- A source link is a derived compatibility projection, not an operator mapping
  authority. Open history intervals are closed before detaching a live link.
- Retained PowerShell aliases are resolver input. They are not copied into
  source evidence or treated as a connector authority.
- The resolver runs only after every organization observation and its grouped
  records are detached, so no old attachment can short-circuit its name ladder.

## Steps

1. Measure active links, alias tiers, decisions, candidates, and grouped
   observations. Complete.
2. Detach live client links and observation assignments under an advisory lock;
   preserve history, reset stale candidate resolution state, then run resolver
   and derived link projection. Complete.
3. Compare reattached, unresolved, and ambiguous groups and their findings;
   correct presentation gaps if found. Complete for the data rebuild.

## Checkpoint

Production baseline: 320 active client source links, all with
`system.compatibility_backfill`; 320 active attached organization observations
and 18 unattached. Alias tiers: 4 manual, 42 seed, 5 alignment. Current mapping
decisions are 37 `legacy_alias` explicit decisions and no operator decisions.
This confirms the displayed unrelated names were inherited compatibility
attachments, not recorded operator choices.

Rebuild result: closed all 320 open client-link history intervals, removed the
320 live client link projections and their 320 dependent attribute-projection
cache rows, detached 320 organization and 18,303 grouped records, then ran the
native resolver. It attached 313 groups and derived 313 new live client links.
It reapplied 37 retained PowerShell-alias decisions against the new link IDs.
25 active groups remain unattached, represented by 15 open candidates and 18
open `client_unattached_group` findings (the difference is expected where
multiple source records normalize to the same candidate or have no usable
name). The earlier 37 legacy decisions remain as immutable orphaned audit
history; the replacement decisions reference current links.

## Next action

The requested rebuild is complete. Before any future intentional reset, make
this audited procedure a versioned operator job rather than repeating an
interactive production operation.

---

# Unified Jobs framework

## Status

**Implementation complete; GitOps deployment and live verification remain
external.** The v1 ledger, durable
schedules, resource-aware isolated workers, domain queue ownership, operator
surfaces, v0 cutover, and registered maintenance work are implemented. The
current slice activates completion dependencies and declared workflow graphs;
remaining work is a requirement-by-requirement audit and correction of any
dishonest handler outcomes, shutdown gaps, or health-surface gaps. ADR-0024's
detailed contract and migration companion remain the design authority.
Preserve unrelated untracked root `.work/probe_*` and bootstrap files.

On 2026-09-28 the user authorized autonomous completion of the Jobs work,
including needed corrections, commits, and pushes. Preserve the unrelated
client-mapping and root `.work` work. The user explicitly prohibited direct
Portainer deployment because deployment is automatic. The latest read-only
production check found the Ninja containers absent and stack 16 inactive, with
its recorded revision still at `a235d6f`; therefore migrations after that
revision and live behavior remain unverified. Do not invoke Portainer.

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

Fourth recovery checkpoint (2026-09-25): production additionally requires a
non-null `drilldown_evidence_key`. The mapping type now supplies the contract's
empty value, correctly leaving device drill-through disabled for an admin-only
finding. The failed transaction rolled back. Next action: validate, deploy the
revised seed, and confirm 0202 completes before activating taxonomy version 7.

Fifth recovery checkpoint (2026-09-25): the finding-type row and bridge now
pass, but the policy creation function requires every registered finding type
to appear in both policy definitions and taxonomy exactly once. The 0202 seed
now adds the matching definition as well as the taxonomy membership. The full
migration remains transactional and rolled back. Next action: validate, push,
and verify successful startup before any policy activation.

Policy activation simplification (2026-09-25): approved to remove the
mandatory separate review gate that prevents a completed policy from becoming
live. Scope: retain validation, the required activation reason, advisory lock,
assessment invalidation, and audit record; remove only the prerequisite review
lookup/function condition and the redundant Django Admin review action. Keep
historical review data intact and do not grant a new role or bypass policy
  validation. Validation: migration consistency, Django checks, targeted policy
  tests, and review of the generated function SQL. Next action: implement the
  additive migration and simplified activation action.

Activation simplification checkpoint (2026-09-25): migration 0203 replaces
the activation function with the same validity check, advisory lock, and
assessment invalidation but no review-table prerequisite. The sole Django
Admin action retains permission and required-reason checks and writes the
activation audit event; the redundant review action is removed. Historical
review data and function remain untouched. Next action: run focused checks,
then request approval to commit and deploy the migration.

Deployment-driven policy checkpoint (2026-09-25): approved to remove the
remaining activation action and reason requirement. Migration 0204 makes the
validated policy-creation function activate the committed version in the same
transaction, retains structural validation, serialization, and assessment
invalidation, and activates already-committed taxonomy 7. The Django Admin
policy form no longer exposes review or activation actions; a manually created
policy is committed/active in one audited save. Next action: validate the
function and admin changes, then request approval to commit/push/deploy.

Client-page recovery (2026-09-25): production logs show `/orgs/all-data-health/`
failing because runtime code still reads the restricted
`v_client_source_link`. Scope: replace every Operations runtime client-source
read with `v_client_source_mapping_effective` / `client_source_references`,
which is the approved mapping evidence projection and is readable by
`operations_app`; leave Django Admin's model registration unchanged. Validate
client workspace and findings tests, then request approval to deploy the
recovery.

Client-page recovery checkpoint (2026-09-25): completed and deployed in
`481708d` (pushed to `origin` and `a-m-rose`). Validation passed: Django
checks, migration-drift check, 67 focused client-workspace/findings tests,
Ruff F checks, and diff check. Portainer deployed the same config hash;
`ninja-operations` is healthy and `/healthz` returns 200. An unauthenticated
request to `/orgs/all-data-health/` now returns the expected 302 login
redirect, with no new restricted-view error in the Operations logs. No schema
migration was required. The authenticated page should be verified from the
operator session as the final UI check.

Production follow-up (2026-09-25): authenticated `/sources/` and
`/orgs/all-data-health/` still fail because
`v_client_source_mapping_effective` is owned by `operations_view_owner` and
its nested, security-invoker `v_client_source_link` rejects that owner. The
application role can select the link view directly. Add migration 0205 to
grant only `SELECT` on the nested view to its owning effective projection;
this repairs every consumer of the approved projection without restoring
runtime reads from the legacy view.

Client-name issue usability follow-up (2026-09-25): the unified Issues table
must show the complete source-name evidence for a canonical client, not only
the source that refreshed the finding. Its control must deep-link to the
single source-link mapping decision, rather than the unfiltered Admin health
page. Extend the effective-reference helper with the source-link identity;
use it to render the evidence and a targeted Operations mapping URL.

Effective-mapping permission correction (2026-09-25): after 0205, an
operations-app query demonstrated the projection then stopped at
`client_source_mapping_decisions`. This is not a runtime grant: the
security-barrier projection is intentionally owned by
`operations_view_owner`, which already has the needed source-link and
observation reads. Migration 0206 grants that owner only `SELECT` on the
decision history table it joins; the app continues to access it only through
the permitted effective projection.

Client mapping recovery and usability checkpoint (2026-09-25): completed in
`0c3e37b`, pushed to both remotes and deployed by Portainer. Migration 0206
applied successfully; `ninja-operations` is healthy and the effective mapping
view returns 320 rows when queried as `operations_app` with tenant context.
The Issues UI now exposes complete attached source-name evidence and deep-links
to the matching Operations mapping decision. Focused client-workspace/findings
tests (67), Django checks, migration-drift checks, focused lint, and diff
checks passed. No new restricted-view error appeared in the post-deploy logs.

Conflict presentation correction (2026-09-25): the legacy Admin rows are real
client-name mismatches, not invalid data. The prior UI flattened every source
group attached to a client, which implied unrelated groups were part of one
conflict. Render the finding's reported source name separately and list only
different literal names from other sources as explicit comparisons.

Exact-name comparison correction (2026-09-25): normalization is permitted for
identity attachment, but it must not suppress a client-name finding. The
resolver and Issues comparison now treat any non-identical reported source
names as different, including punctuation, spacing, hyphenation, and case.

Client mapping inventory completion (2026-09-28): in progress. Keep the
top-level Clients page as a status dashboard. Add Inventory > Clients as the
operator-facing canonical-client inventory, with compact source-record,
literal-name-difference, review, and unmapped-candidate counts. Rebuild
Operations Admin > Integrations > Client mappings as the complete lifecycle
surface: effective attachments, open unattached candidates, and active
collision/duplicate-group findings must all be visible through explicit
filters, with source evidence, current decision/provenance, decision history,
and direct action/detail links. Do not introduce an expected-source absence
finding until a client-source coverage policy exists. Reuse the existing
candidate acceptance/map/exclude lifecycle; do not write source evidence
directly to canonical entities.

Scope: `apps/core/views.py`, `config/urls.py`, navigation, the mapping template,
and a new Inventory Clients template. No schema migration is planned because
the approved effective mapping projection, decision history, candidate queue,
and findings already persist the needed state. Validation: Django checks,
focused request/template tests, Ruff, and diff check. Checkpoint: inspect the
existing effective-mapping/candidate paths, then implement the two read models
and links before adding focused tests.

Completion checkpoint (2026-09-28): implemented the two read models. Inventory
now opens on Clients and has a Clients sub-navigation item before Computers;
it lists canonical clients with attached source-record, literal-name-difference,
and review counts, while preserving the existing Clients status dashboard.
Operations Admin > Integrations > Client mappings now shows all effective
attachments with decision provenance/history, all candidate lifecycle records
(including resolved history), and active ambiguity/collision findings, with
source, client, candidate, and finding links. Validation passed: Python
compile, 14 focused inventory/navigation tests, Ruff F/I for changed Python,
and `git diff --check`. The local `manage.py check` cannot run because this
workstation interpreter cannot import the repository `shared` package; Docker
Compose has no local services, so rendered request/database validation remains
for the deployment environment. No migration or deployment has been performed.

Client overview presentation correction (2026-09-28): in progress. The
individual client overview must not repeat opaque source IDs and provenance as
its primary source-reference table. Keep the reported source name and current
state visible, and add direct Source record and Mapping decision detail links.

Source-record drilldown completion (2026-09-28): implemented locally. The
Source record link now targets one exact client/source attachment rather than
the generic Sources list. Its detail surface includes reported name, source
identifier/namespace, observation and presence timing, current attachment,
decision rationale/provenance, and decision history; mapping action remains a
separate direct link. Validation passed: Python compilation, 14 focused
navigation tests, Ruff F/I, and `git diff --check`. Pending commit/push.

Sources/mappings boundary correction (2026-09-28): implemented locally. Admin
Sources is source-health, collection-volume, and run-history only; it no
longer duplicates source-client identity rows. Each source card hands off to a
source-filtered Client mappings view, which is the exclusive attachment,
ambiguity, candidate, and decision-lifecycle surface. The shared Admin
navigation is stable across Overview and integration pages, with distinct
Client mappings, Client candidates, and Entity candidates labels. Pending
validation and commit/push.

Completion checkpoint (2026-09-28): validation passed: Python compilation, 14
focused inventory/navigation tests, Ruff F/I for changed Python, and `git diff
--check`. Admin home now has a Client mappings card with live review,
unassigned-candidate, and ambiguity counts. No migration is required. Next
action: commit the completed navigation and page-boundary correction, push both
remotes, and trigger the required GitOps redeploy.

Resolver recovery (2026-09-28): production startup exposed an existing
client-name resolver defect while it refreshed source identity: it attempted
to write `resolved_at` on `operations.findings`, whose lifecycle field is
`closed_at`. Correct both entity-finding closure paths and test the contract;
AdminFinding and client-candidate closure fields remain unchanged.

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

Autonomous correction checkpoint (2026-09-28): migration 0207 fixed the
claim-result API by returning both the claimed run ID and fencing token through
one restricted function. Focused migration tests, Python compilation, targeted
Ruff, and `git diff --check` passed. It was committed as `43b2fbc`, pushed to
`origin` and `a-m-rose`, and Portainer redeployed the approved commit. The
Portainer stack reports the matching configuration hash; Operations startup
logged `Applying operations.0207_jobs_claim_result_api... OK`, `/healthz`
returned 200, and Operations, ingest, and Postgres are healthy. The direct
Portainer POST/PUT redeploy attempts were rejected by its bodyless helper API,
but the configured one-minute Git redeploy detected and completed the push.
Next action: add deterministic immutable registry snapshot registration and
then convert v1 admission/claim consumers without falling back to raw ledger
lookups.

Definition registration checkpoint (2026-09-28): the shared Jobs registry now
produces deterministic, credential-free immutable snapshot metadata and a
SHA-256 digest. Ingest registers every declared snapshot transactionally under
the ingest tenant before operational execution begins. This establishes the
definition catalog without enabling a v1 producer or worker. Validation
passed: Python compilation, targeted Ruff (`E`, `F`, `I`) for the registry and
test, targeted undefined-name lint for the touched ingest modules, 10 focused
registry/queue tests, and `git diff --check`. Next action: commit, push, and
verify the production deployment registers the snapshot catalog cleanly.

Startup-order correction (2026-09-28): production validation exposed that the
initial registration placement ran before `db.init`, leaving ingest in a
restart loop. Registration now runs immediately after the pending ingest
migrations, before recovery or scheduled execution. A focused source-order
test prevents that regression. Validation passed: Python compilation, scoped
Ruff, 11 focused registry/queue tests, and `git diff --check`. Next action:
commit and deploy the startup-order fix, then verify ingest health and catalog
registration.

Production-observed catch-up correction (2026-09-28): after the startup-order
fix restored ingest, its normal startup exposed an existing PostgreSQL
`IndeterminateDatatype` error in the optional software-classifier mode probe.
Both nullable parameters are now explicitly `text`, preventing false
"overdue" decisions and unneeded classifier catch-up work. Python compilation,
undefined-name lint, and `git diff --check` pass; the dedicated focused module
is skipped locally because this environment cannot import the ingest runtime.
Next action: deploy and verify that startup no longer logs the probe error.

Deployment verification (2026-09-28): `780ee81` is deployed to both remotes
and resolved by Portainer. Ingest and Operations health endpoints return OK;
the fresh ingest startup has no catch-up probe error and reaches ready state.
The Jobs definition catalog contains 30 immutable registered snapshots, one
for each declared registry definition. The direct Portainer redeploy endpoint
continues to reject bodyless POST requests (HTTP 405), while the configured
one-minute Git update applied each approved revision. Next action: proceed with
the next governed v1 consumer conversion without reintroducing raw ledger
access.

Worker API foundation (2026-09-29): added migration 0208 with restricted
ingest-only v1 APIs that return a claimed run ID, fencing token, and job key
atomically, increment attempts under that fence, and finish/release the claim
without a worker reading or mutating the Jobs ledger directly. This remains
dormant until worker conversion; existing version-0 traffic is unchanged.
Focused validation passed: Python compilation, targeted Ruff, 12 Jobs
migration tests, and `git diff --check`. Next action: deploy this additive API
and implement the dedicated worker process against it.

Worker API deployment (2026-09-29): committed as `8b1322a`, pushed to both
remotes, and applied by Portainer. Operations logged
`Applying operations.0208_jobs_v1_worker_api... OK`; Operations and ingest
remain healthy. Next action: add the dedicated worker process and Compose
topology, using only the restricted v1 APIs for converted work.

Dedicated worker topology (2026-09-29): added migration 0209 for fenced v1
progress/heartbeat writes, `ingest.jobs_worker` as a no-HTTP/no-scheduler
process, and the `jobs-worker` Compose service with its own health signal.
The worker claims, progresses, and finishes converted runs through the
restricted APIs; existing version-0 producers remain unchanged, so it starts
idle until the producer cutover. Focused validation passed: Python
compilation, targeted Ruff, four worker/migration tests, Compose config, and
`git diff --check`. Next action: deploy the worker topology and confirm its
health before converting the first producer family.

Worker topology deployment (2026-09-29): committed as `a1a3667`, pushed to
both remotes, and applied by Portainer. Operations logged
`Applying operations.0209_jobs_v1_progress_api... OK`; the dedicated worker,
ingest, and Operations are healthy. The worker initialized its own database
pool and definition catalog and is correctly idle because no producer has yet
created a version-1 run. Next action: convert operator-originated Job requests
to the constrained APIs, then verify a bounded first family executes through
the dedicated worker.

Operator producer conversion (2026-09-29): the Operations Jobs request,
retry, batch, and software-rebuild paths now call `jobs_request` or the
declared Software supersession API with an immutable registry digest and a
credential-free request identity. They no longer insert or supersede ledger
rows directly. Focused validation passed: Python compilation, undefined-name
lint, 11 operator-queue/registry tests, and `git diff --check`. Next action:
deploy this conversion and verify a bounded operator request completes through
the dedicated worker before converting automatic schedules.

Operator producer deployment (2026-09-29): committed as `ffcdc57`, pushed to
both remotes, and resolved by Portainer. Operations and the Jobs worker are
healthy. A live operator request was not created during this deployment
verification, so first-run execution remains to be confirmed through the
normal operator surface before automatic schedules are cut over. Next action:
implement persistent schedule state and leader-elected automatic request
production, then exercise one bounded converted request.

Automatic-admission recovery (2026-09-29): the first automatic v1 software
request encountered a still-active version-0 run. The admission API correctly
rejected the incompatible overlap, but the automatic scheduler allowed that
exception to terminate ingest. `aa02a73` now logs and defers incompatible
automatic admissions. It is deployed to both remotes and Portainer reports
the matching configuration hash. External verification confirms
`operations-ingest` and `ninja-jobs-worker` are healthy with zero restarts;
ingest is completing scheduled work and the worker remains ready. The separate
platform-findings tenant-context error remains contained by its existing
failure boundary and was not changed. Next action: implement durable,
leader-elected schedule production only after explicitly reconciling or
draining active version-0 work for each converted family.

Durable schedule cutover (2026-09-29): in progress. Migration 0212 adds the
restricted schedule reconciliation and due-schedule read APIs. Ingest now
persists resolved UTC cadence and capability state, uses a PostgreSQL advisory
leader during each durable due-tick pass, coalesces missed ticks past the
current time, and submits requests through the existing atomic schedule API.
The legacy automatic producer and startup catch-ups are retired, avoiding
duplicate producers; a still-draining version-0 family is isolated as a
deferred schedule rather than rolling back other due work. Next action:
commit, deploy, and externally verify schedule activation and a bounded first
due request before implementing v1 timeout/cancellation/recovery controls.

Lifecycle and domain conversion checkpoint (2026-09-29): commits `a235d6f`
through `51ffe88` added governed cancellation requests, absolute v1 deadlines
with conservative resource containment, per-lane child-process execution,
supervisor control-plane resilience, additive source-domain Job links, and
registered source-action/source-demand workers. Source demand no longer starts
a daemon thread; demand-aware schedule enablement prevents idle no-op history.
The next conversion routes registered ingest HTTP triggers through v1
admission, leaving only genuinely scoped/legacy/bootstrap paths for separate
review. Focused registry, topology, migration, compilation, and diff checks
passed for the individual commits.

Operational blocker (2026-09-29): read-only host verification found every
Ninja container absent. Portainer stack 16 reports inactive, automatic update
has no JobID, and its last deployed revision is `a235d6f`; later pushes are not
deployed. The user explicitly prohibited direct Portainer deployment, so no
restart/redeploy was attempted. Continue implementation locally, but final
production validation requires the automatic updater/stack to be restored
outside this task or new explicit recovery direction.

Schedule presentation checkpoint (2026-09-29): the Jobs catalog now reads
tenant-scoped `job_schedules` state as the schedule authority. Scheduled rows
show persisted capability state, next due time, and the last request outcome;
conditional source-domain schedules distinguish waiting for demand from a
disabled capability. Focused Jobs tests, Python compilation, and diff checks
pass. Next action: harden and populate the source-demand/source-action Job-run
links with same-tenant constraints and lifecycle ownership.

Source-domain ownership checkpoint (2026-09-29): migration 0218 corrects the
preparatory single-column Job references to same-tenant composite references,
adds the tenant-1 boundary and RLS to the legacy source-demand queue, and adds
RLS to source actions. Governed workers attach each claimed domain row to the
exact Job run before execution. Retained domain failures now fail the wrapper
Job instead of appearing successful. Focused migration/topology tests and
Python compilation pass; PostgreSQL migration execution remains unavailable
while the stack is inactive. Next action: inventory and convert the remaining
direct/background execution paths, beginning with maintenance and bootstrap
work that still bypasses durable admission.

Software-demand cutover checkpoint (2026-09-29): both scoped software forms
now retain demand rows and wait for the registered software queue Job. The
former direct scoped daemon thread and the demand queue's immediate worker
thread are removed; the governed drain processes demand before activity and
scheduled work. The static Jobs inventory was regenerated from its checked
discovery function. Focused inventory/operator tests and compilation pass.
Next action: add immutable per-attempt Job membership for all three software
domain queues, then make partial queue failures fail the owning Job.

Software-domain ownership checkpoint (2026-09-29): migration 0219 adds
tenant-safe Job links to all three legacy software queues and an immutable
`job_domain_attempts` journal shared by software and source-domain claims.
Each claim records its owning run and attempt before work starts; software
demand, activity, and scheduled rows share one bounded drain, and any item
failure now fails the owning wrapper Job while retaining retry state. The
software queues enforce the current tenant boundary and RLS. PostgreSQL
execution remains unverified while the stack is inactive. Next action: remove
the dormant version-0 producers/workers and convert direct maintenance work
to registered control Jobs without letting recovery depend on normal lanes.

Producer cleanup checkpoint (2026-09-29): ingest now registers one automatic
producer only: the durable schedule poller. All legacy per-definition
APScheduler registrations and startup catch-up admissions are removed, along
with the unreachable HTTP daemon-thread handlers hidden behind governed
dispatch. The scheduler still hosts bounded control/recovery loops and the
temporary version-0 drain needed for pre-cutover rows. Static inventory,
focused Jobs tests, and compilation pass. Next action: define the controlled
version-0 queue cutover and move ordinary maintenance mutations into explicit
Jobs, leaving only claim containment and service liveness outside normal lanes.

Maintenance conversion checkpoint (2026-09-29): source-demand lease recovery,
stale diagnostic-run recovery, and platform-health evaluation are now three
registered, durably scheduled service-lane Jobs. Their former direct scheduler
callbacks and startup run-log mutation are removed. Claim timeout containment,
legacy-v0 interruption recovery, HTTP liveness, and infrastructure bootstrap
remain direct control-plane duties by design. Registry/inventory tests,
compilation, and diff checks pass. Next action: quiesce or preserve any queued
version-0 runs through an explicit cutover migration, then remove the legacy
in-process v0 worker and recovery callbacks.

Version-0 cutover checkpoint (2026-09-29): migration 0220 truthfully
terminalizes any remaining active v0 rows without deleting history: queued
runs become Cancelled and running runs become Needs attention, both with
retry/review guidance and events. The in-process v0 worker, heartbeat, raw
ledger mutation, startup recovery, and stale watchdog are removed. All new
execution now uses fenced v1 APIs and isolated child processes. Focused tests,
compilation, undefined-name lint, and diff checks pass; migration execution is
pending because the stack remains inactive. Next action: complete dependency
runtime semantics and expose workflow/run detail from the common ledger.

Run-detail checkpoint (2026-09-29): Job activity now exposes the selected
run's event timeline, prerequisite and dependent edges, linked domain attempts,
contract version, scope, immutable definition digest, correlation/retry links,
parent link, and terminal reason. This gives the dependency runtime a truthful
operator surface before production edges are activated. Focused Jobs tests,
compilation, and diff checks pass. Next action: implement atomic workflow
admission plus success release and prerequisite-failure propagation.

Dependency-runtime checkpoint (2026-09-29): the shared registry declares
completion successors for patch collection and software queue draining. Both
operator and automatic admission create the full graph atomically, including
the patch-classification/resolver join before platform evaluation. Migration
0221 adds an idempotent completion-edge API, releases ready children on
successful completion, and recursively marks queued descendants Needs
attention when a prerequisite fails, is cancelled, or times out. Material
revision dependencies remain distinct and unchanged. Focused registry,
migration, operator, inventory, and worker-topology tests pass (22 tests), as
do Python compilation, undefined-name lint, and `git diff --check`; PostgreSQL
execution remains unavailable while the stack is inactive. Next action: audit
every executable handler for truthful failure/result behavior, then close
worker-shutdown and Admin Health parity gaps found by the final requirements
review.

Handler-truth checkpoint (2026-09-29): required patch and Ninja collection
substeps now continue independently but fail the owning Job after all safe
steps finish. Identity and source collectors retain partial outcomes while
propagating aggregate failure after required projections. Retention and
Windows/end-of-life projections no longer suppress failure, and failed
notification or digest deliveries fail the Job after retaining delivery
evidence. The Agent compliance resolver follow-up is now a declared atomic
dependency rather than a later request. Focused source-failure, condition
safety, registry, operator, inventory, and worker-topology tests pass, with
Python compilation, undefined-name lint, and diff checks. Next action: enforce
the accepted workflow-root rule so a requested root remains Waiting until all
required descendants complete, then audit worker shutdown and health parity.

Workflow-root checkpoint (2026-09-29): migration 0222 distinguishes handler
completion from requested-work completion. A successful run with required
children releases its resource claims and deadline, clears its worker fence,
and remains visibly Waiting without consuming execution capacity. Terminal
child state is reconciled recursively: all-success rolls Completed up through
diamond joins, while failure or cancellation rolls Needs attention up and
blocks unstarted descendants. Waiting coordinators can be cancelled without a
nonexistent worker acknowledgement. The Job activity UI labels this state
explicitly and does not claim a worker is active. Focused migration, registry,
and operator tests, compilation, undefined-name lint, and diff checks pass;
PostgreSQL execution remains pending while the stack is inactive. Next action:
complete the declared source/intelligence edge families, then close worker
shutdown and Admin Health parity gaps.

Successor/edge-family checkpoint (2026-09-29): migration 0223 replaces the
single queued-or-running key exclusion with one queued successor plus one
executing run; workflow coordinators remain workerless and do not occupy the
executing slot. Generic and Software request APIs now preserve demand arriving
during execution. Broader Software supersession rewires retained workflow
edges to the covering queued run instead of stranding a parent. The registry
now declares source collection/action -> resolver -> platform evaluation and
the intelligence -> matcher/full-classifier families; duplicate inline source
resolution was removed, while required CMDB evaluation remains in the source
handler and now propagates failure. Focused migration, registry, source safety,
inventory, operator, and topology tests pass (59 tests), along with Python
compilation, undefined-name lint, and diff checks. Next action: make worker
shutdown explicitly terminate/reconcile children and add registry/scheduler/
worker mismatch evidence to Admin Health.

Worker-shutdown checkpoint (2026-09-29): migration 0224 adds a fenced worker
interruption transition. On graceful supervisor shutdown, exited children use
their normal terminal transition; still-running unaudited handlers become
Needs attention, lose their ledger fence, retain contained resource claims,
and block required descendants before the container owns process teardown.
The supervisor never calls terminate or kill because no handler is certified
kill-safe. Focused migration/topology tests, compilation, undefined-name lint,
and diff checks pass. Next action: replace the provisional broad source and
intelligence completion chains with dependency metadata and revision-aware,
affected-scope admission required by ADR-0024, then add Jobs control-plane
health evidence.

Revision-dependency checkpoint (2026-09-29): the provisional completion-only
edges are replaced with named revision contracts and condition-aware
admission. Migration 0225 validates each edge against the prerequisite's
immutable definition snapshot, persists scope/condition/coalescing/failure
metadata, publishes successful output revisions, and rechecks exact freshness
before release. CMDB evaluation is a separate registered Job. Source-demand
and source-action handlers publish bounded source-type signals. Intelligence
handlers retain integer compatibility but now report material change
explicitly; unchanged upserts do not count, and the full CVE matcher compares
semantic before/after output sets. Job detail exposes requested/input/output
revisions and edge contracts. The checked inventory was regenerated. Focused
Operations tests pass (20), focused ingest/material/projector tests pass (67),
and Python compilation, undefined-name lint, and `git diff --check` pass.
PostgreSQL execution remains unavailable while the stack is inactive. Next
action: commit and push this slice, then add Jobs registry/scheduler/worker,
claim-containment, and policy mismatch evidence to Admin Health and expose the
remaining persisted control-plane data.

Control-plane diagnostics checkpoint (2026-09-29): in progress. Migration
0226 adds tenant-protected scheduler/worker heartbeat storage and restricted
heartbeat/stop APIs. A read-only administrator API provides paginated access
to every persisted Jobs control relation: definition revisions, schedules and
ticks, request aliases, runs and events, dependencies, domain attempts,
lane/resource policy and claims, and runtime heartbeats. The new Jobs control
plane page exposes those records without direct table grants. Admin Health
compares the stored definition/schedule/policy state and fresh runtime registry
digests against the shared registry, and flags missing runtimes or contained
claims. The final schema-name review also corrected the run-detail query from
the nonexistent `requested_input` name to the authoritative `request_payload`
column before this slice was committed. Focused Operations tests pass (65),
focused registry/material tests pass (16), Django system checks pass, and
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the stack is inactive. Next action:
review and commit/push this slice, then complete Job activity filters/
pagination and remaining request/schedule outcome semantics before the final
requirement audit.

Job activity checkpoint (2026-09-30): in progress. The activity query now has
bounded durable pagination with a count, filtering for Job, source/client
scope, lane, origin, status, owner, correlation/batch identifiers, requested
date range, and technical lineage identifiers. System run-log history is
separately counted and paginated, so neither list silently truncates. The
Jobs home asks the same authoritative run query for the finite set of active
definition states rather than relying on an arbitrary 200-row cap. Focused
validation passed: five Jobs/UI tests, Django system checks, Python
compilation, undefined-name lint, and `git diff --check`. PostgreSQL-backed
request checks remain unavailable while the local stack is inactive. Next
action: commit/push this slice, then add durable terminal schedule outcomes
and continue the requirement audit.

Schedule terminal-outcome checkpoint (2026-09-30): migration 0227 makes
`job_schedules.last_outcome` authoritative for the terminal result of its
current `last_run_id`. An `AFTER UPDATE OF status` security-definer trigger
handles every completion path and refuses to overwrite a schedule that has
advanced to a newer request; an additive backfill corrects prior terminal
schedule rows. Focused migration/Jobs tests (7), Django system checks, Python
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the local stack is inactive. Next action:
commit/push this migration, then audit and implement remaining actionable
Admin Health findings and cross-surface Job links.

Admin Health persistence correction (2026-09-30): before adding the remaining
Jobs conditions, the existing platform-health evaluator was found to import an
entity-finding helper despite its admin-only contract. It now writes its
deduplicated source-failure and queue-stall conditions to
`operations.admin_findings`, preserving the condition assessment participant
contract. Focused condition-safety tests (37), Python compilation,
undefined-name lint, and `git diff --check` pass. Next action: commit/push
this regression correction, then register and evaluate the seven required
Jobs health conditions.

Jobs health policy checkpoint (2026-09-30): migration 0228 registers the
seven required Jobs Admin Finding types under platform health and clones the
active condition policy into a new validated revision with a Jobs control-plane
taxonomy entry. The shared policy carries the same definitions, preventing a
code-only condition taxonomy. Policy parsing, Python compilation, and
`git diff --check` pass. Next action: commit/push the policy prerequisite,
then implement the evaluator's seven measured, deduplicated conditions and
their Job deep links.

Evaluator handoff: implement the seven measurements in
`ingest/platform_findings.py` using durable Jobs schedules, runs,
dependencies, queue registry, immutable definition revisions, and runtime
heartbeats. Each emitted detail must retain `job_key`, `job_run_id`, or
schedule/control-plane section data for the Admin Health deep link; resolve
only after a fresh governing condition assessment permits clearing.

Jobs health evaluator checkpoint (2026-09-30): migration 0229 exposes a
tenant-bound, security-definer measurement API to the platform-health Job,
so the ingest role does not gain direct access to control-plane tables. The
evaluator now emits all seven policy-registered conditions from durable
schedules, run outcomes, dependencies, queue policy, immutable definition
snapshots, lane/resource policy, and runtime heartbeats. Queue and dependency
age thresholds come from the `operator.jobs` registry; repeated failures and
timeouts retain a bounded 24-hour observation window. Each finding has a Job
activity run/definition link or a control-plane section link. Focused
condition-safety and Jobs/migration tests, Django checks, compilation,
undefined-name lint, formatter checks for changed implementation files, and
`git diff --check` pass. PostgreSQL execution remains unavailable while the
local stack is inactive. Next action: review the full requirements against the
current framework, correct any remaining cross-surface or handler gaps, then
commit/push this evaluator slice with this checkpoint.

Audit correction in progress (2026-09-30): the inventory identified Metabase
bootstrap as an ungoverned daemon-thread path at startup and on the legacy
HTTP endpoint. It is explicitly classified as maintenance work by the Jobs
contract, so it is being registered as a capability-gated service Job and
admitted through the existing request API. HTTP serving and the scheduler
remain service infrastructure rather than Job work. The bootstrap result must
be truthful: disabled configuration creates no run, while configured but
unavailable or incomplete Metabase fails the Job for explicit manual retry.

Metabase bootstrap correction checkpoint (2026-09-30): `metabase-bootstrap`
is now a registered, capability-gated maintenance Job. Startup and the
`POST /bootstrap-metabase` endpoint admit it through the durable request API;
the prior daemon threads are removed. Disabled configuration returns no Job,
and a configured external dependency that is unavailable or incomplete makes
the Job fail rather than logging a false success. The checked registry
inventory was regenerated, retaining its coverage metadata. Focused inventory,
registry, and Jobs UI tests (22), Django checks, Python compilation,
undefined-name lint, and `git diff --check` pass. PostgreSQL-backed admission
and external Metabase execution remain unavailable while the local stack is
inactive. Next action: commit/push this audit correction, then continue the
full requirement audit for any remaining ungoverned background paths or
cross-surface gaps.

Timeout-contract correction in progress (2026-09-30): the review found that
the durable claim path still assigned one hard-coded 90-minute deadline and
definition snapshots did not describe timeout, progress, result, or
permission contracts. Add those immutable registry fields to every snapshot
and introduce a fenced v4 claim API that derives the deadline from the
claimed revision. Existing v1 snapshot rows without the new field retain the
previous 90-minute behavior only as backward-compatible historical input.

Timeout-contract correction checkpoint (2026-09-30): immutable definition
metadata now contains timeout, retry, stage-progress, result, and permission
contracts. Migration 0230 adds a tenant/fence-preserving v4 claim API, which
reads the claimed immutable snapshot and records its timeout in the run. The
v3 90-minute fallback is reachable only for historical v1 snapshots that
predate this contract; every newly registered revision carries its own value.
Focused inventory/registry/Jobs worker/UI/migration tests (26), Django
checks, Python compilation, undefined-name lint, and `git diff --check` pass.
PostgreSQL execution remains unavailable while the local stack is inactive.
Next action: commit/push this contract correction, then continue the full
requirement audit.

Priority-contract correction in progress (2026-09-30): admission still got
the legacy table default priority instead of an immutable definition contract.
Add priority, coalescing scope, and concurrency scope to every snapshot, and
apply the definition priority in a fenced `BEFORE INSERT` trigger for v1 run
admission. This keeps the existing priority-aging claim order but removes an
untracked request-time default.

Priority-contract correction checkpoint (2026-09-30): snapshots now include
priority, coalescing scope, and concurrency scope alongside the previously
added timeout/progress/result/permission contracts. Migration 0231 applies
the immutable priority with a security-definer, before-insert trigger for v1
Jobs, while preserving legacy rows and the reviewed priority-aging claim
order. Focused registry/worker/UI/migration tests (22), Django checks, Python
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the local stack is inactive. Next action:
commit/push this correction and continue the full requirement audit.

Cross-surface correction in progress (2026-09-30): active source-demand rows
already retain their same-tenant `job_run_id`, but the Sources page displayed
only a generic queued/running label. Expose a direct Job activity link from
that durable relationship; do not derive a link from run-log diagnostics.

Cross-surface correction checkpoint (2026-09-30): Sources now queries active
source demand under tenant context and renders its retained Job-run link for
queued or running work. Focused Jobs UI tests (7), Django checks, and `git
diff --check` pass. Next action: commit/push this correction, then complete
the remaining requirement audit.

Completion audit checkpoint (2026-09-30): the full governed Jobs scope is
implemented in the current branch. The shared immutable registry now records
owner, technical key, presentation, capability, cadence/trigger, lane,
resource/concurrency/coalescing scope, dependency contracts, priority,
timeout, retry, progress, result, permission, and handler revision; its
machine-checked inventory covers registered dispatchers, schedules, HTTP
admission paths, queues, startup work, and the remaining service threads.
Every converted invocation is admitted before execution, domain attempts link
to their Job run, and all Jobs readers use the durable ledger/schedule/control
relations rather than run-log lifecycle state. The worker uses fenced APIs,
isolated children, contained timeouts, cooperative cancellation, immutable
revision dependencies, and explicit stalled/blocked outcomes. Jobs Admin
Health has all seven governed, deduplicated, actionable measurements with
durable Job/control-plane links; Sources has the active demand-to-Job link.

Validation: `pytest apps/core/tests/*jobs*.py` passed (57), `python manage.py
check` passed, Python compilation and undefined-name lint passed for each
changed implementation slice, and `git diff --check` passed. Relevant pushed
commits include `c5df42c`, `62e2b8a`, `f0836c0`, `622555f`, and `83cc24e`.
The local PostgreSQL stack is inactive, so migration execution, runtime
admission/claim behavior, and automatic GitOps deployment cannot be directly
verified here. Per user direction, do not call Portainer; origin pushes are
the deployment handoff. No legacy data/history is deleted or fabricated.

Production regression correction in progress (2026-09-30): read-only SSH
health validation after the automatic deployment found `operations-ingest`
restart-looping because `SCHEDULED_OPERATOR_JOB_KEYS` omitted five registered
durable maintenance schedules. The fail-closed registry check correctly
prevented a partial scheduler from running, but its test inspected obsolete
direct scheduler declarations rather than the parity constant. Restore exact
membership and test the parsed constant against `scheduled_definition_keys()`.

Production regression correction checkpoint (2026-09-30): restored the five
omitted schedule keys and added exact parsed-constant parity coverage. Focused
registry/inventory/Jobs UI tests (24), Django checks, Python compilation,
undefined-name lint, and `git diff --check` pass. Next action: commit/push
the correction and use read-only SSH health checks to verify the automatic
GitOps restart; do not call Portainer.
