# 0024 — Unified Jobs execution contract

Status: Three rollout decisions accepted; detailed contract proposed, not implemented
Date: 2026-09-24

## Review boundary

This is the step 1.1 architecture proposal. The user retains design decisions.
It is not authorization to add migrations, change grants, start workers, or
deploy. The companion [migration design](0024-unified-jobs-migration-design.md)
identifies proposed schema changes and their acceptance tests. Executable SQL
and PostgreSQL integration validation are still required before the plan's
step 1.2 migration approval gate can pass.

Step 0.2 remains a prerequisite: the current inventory is a list of names,
not the required per-entry handler, scope, side-effect, prerequisite, result,
retry, and cancellation audit. Its tests establish only the categories they
actually scan. No existing handler is certified idempotent or kill-safe by
this document. Source-specific identifiers and customer data do not belong in
the shared registry or checked-in evidence.

## Verified starting point

At repository baseline `e6bc64b`:

- `ingest/operator_job_queue.py` has five lanes, one process-local semaphore
  of two, a 90-minute heartbeat lease, and synchronous handler execution.
  Its heartbeat thread can remain live while a handler is stuck. Lease
  renewal therefore does not establish progress or a bounded execution time.
- Migration 0178 defines active as `queued` or `running`. Stalled rows are
  terminal history; counting them as active invents duplicate execution.
  Neither enqueue path populates `run_log_kind`, so name-based unmatched
  logs do not establish that work ran outside Jobs.
- Source demand uses an unscoped `df` and a direct thread. Migration 0020 has
  no tenant column or RLS. Source actions have a tenant column, but migration
  0160 does not enable RLS. Software scheduled, demand, and activity queues
  also require an ownership audit before tenant-safe linkage can be claimed.
- The operator dispatcher mixes raising lower-level handlers with wrappers
  that swallow errors: resolver, patch-cycle substeps, scoped software,
  end-of-life follow-ups, and several derived projections need explicit
  result review. A normal return does not prove every required step worked.
- Jobs events have tenant RLS, but their Job FK is not tenant-composite and
  deletes cascade from a Job. Migration 0180's title alone does not establish
  an immutable, tenant-consistent journal.
- Notifications record delivery state and audit separately from external
  sends. Source actions can lose an external response after a mutation.
  A Job lease or database transaction cannot make either send exactly once.

Evidence: migrations 0020, 0160, 0178–0182; `ingest/main.py`,
`ingest/derived.py`, `ingest/source_run_queue.py`, `ingest/source_actions.py`,
`ingest/inventory/queue.py`, `ingest/notifications.py`,
`ingest/notifications_digest.py`, and the Operations Jobs views.

## Existing authority conflicts requiring acceptance

`DESIGN.md` section 5 specifies 30-minute stale reset and automatic retries
below a cap. The Jobs proposal instead retains resource ownership when an
execution might still be live and requires reviewed retry eligibility. On
acceptance, this record would supersede that execution policy for converted
queues. Existing domain payloads and retained queue history would survive.

Root architecture requires derived refresh before collection completes.
Current wrappers sometimes catch projection/evaluation failures. The proposed
workflow completion rule below makes required failures observable. Selection
of required versus optional projections must use current consumer authority,
not old comments calling a now-used projector a shadow path.

ADR-0012 and the glossary still govern evidence and state. Jobs coordinates
execution; it does not become an entity store, an evidence projector, a
finding-policy authority, or a source action approval mechanism.

## Proposal A: definition registry and result contract

Use a declarative, standard-library-only module under `shared/`. Django and
ingest import metadata; only ingest imports executable handlers. Definitions
are immutable snapshots addressed by a deterministic digest of normalized
metadata, including the handler version. A historical Job references the
snapshot that admitted it, even after the live definition changes.

Each definition contains the plan's fields plus explicit `kill_safe`,
`retry_class`, `supported_scope`, required output revision names, and a
sanitized result schema. Resource names are dispatch/configuration metadata;
source ownership and identity policy continue to come from platform data.

Requests contain a definition key, authenticated tenant and actor, trigger,
typed scope, bounded payload, request identity, and optional parent and root
run references. Payloads carry stable local references, never credentials,
arbitrary callable names, raw SQL, or vendor response bodies. Scope and
permissions are checked at request time and again before claim; workers
resolve credentials only when executing the approved handler.

Admission rechecks enablement using tenant/source configuration. Disabled
definitions remain visible with a reason and receive no periodic no-op runs.
A startup validator compares definitions, executable handlers, catalog and
schedule configuration, database definition snapshots, and schedule rows.
Missing or duplicate keys prevent readiness. Record mismatch diagnostics for
later Admin Health reconciliation even if the database is unavailable during
the first check. Liveness remains separate from readiness.

Handlers return typed outcomes: success, failure, cancellation, or uncertain
external outcome. Success includes required step outcomes, any factual count,
and material output revisions. A disabled capability or failed single-flight
lock cannot be translated into successful execution. Existing handlers that
return `None`, an integer, or swallow exceptions need reviewed adapters before
conversion. The job runner must not infer success from a `run_log` row.

Enforcement after implementation: duplicate/key/schema tests, import-isolation
tests, request validation, immutable definition rows, and adapters tested by
failure injection. Until those exist this section is a proposed contract.

## Proposal B: durable admission and scheduling

Keep `operations.operator_job_runs` and its existing status values. Use
`queued` plus a structured wait reason for dependencies/resources, and
`failed`/`stalled` plus a terminal reason for Needs attention. A terminal row
records an outcome once; retry creates a linked new run instead of resetting
history. Cancellation of queued work is atomic against claim.

Distinguish three identities:

1. A request identity deduplicates the same HTTP or schedule request even
   after completion. It includes tenant, definition revision, normalized
   scope, and caller-supplied identity or durable due-time identity.
2. An active coalescing key merges equivalent pending demand only when the
   requested input revisions are covered by that run. A later dirty revision
   must survive as a successor request if an in-flight run cannot cover it.
3. A resource claim excludes conflicting execution, including uncertain
   execution whose Job is already terminal. It is not the active-row index.

One transaction creates the run, request alias, initial event, and any domain
record/link. On rollback none exist. Request aliases retain the identity of
coalesced requests; a vanished HTTP response can be retried safely. Broader
queued Software modes may supersede narrower queued modes, with links and
events. Running modes are never silently replaced.

Persist enabled state, eligibility reason, UTC anchor, cadence/time zone,
last due tick, next due time, last request and outcome references, definition
revision, and reconciliation revision. Record skipped/coalesced tick counts
and reasons. An ordinary restart consults this state rather than queuing new
work merely because the process started. Initial activation and cadence
changes need an explicit anchored policy; historical dates are not inferred
from the latest unrelated diagnostic log.

The scheduler holds a leader advisory lock on a dedicated connection and
creates requests only. Schedule row locks and unique due-time request keys
also enforce correctness if leadership is lost during a transaction. Release
leadership when the connection fails. Coalesce overdue ticks deterministically
and calculate the next tick from the persisted anchor, not finish time.
Use the existing scheduler dependency only for wakeups and cron calculations;
no new queue or scheduler dependency is proposed.

## Proposal C: resources, fairness, and dependencies

Claim lane capacity and all required resources in one short transaction,
before starting a child. A successful claim stores the owning run, worker
incarnation, random claim token, and generation. Every subsequent transition
checks that tuple. A stale supervisor cannot finalize a replacement's run.

Resource conflicts must include scope containment: a fleet/tenant writer
conflicts with every narrower writer; independent client/source scopes can
proceed only when neither handler actually writes fleet-wide state. Current
fleet projectors must retain fleet resource declarations until proven scoped.
Equality of strings such as `source:A` and `source:A:client:B` is insufficient.

Proposal for atomicity: lock resource coordinator rows in a stable order,
then lane coordinator rows, then candidate runs; compute scope overlap and
available units while those coordinator rows are locked. All claim, finish,
cancel, supersession, and containment paths use that same lock order. Losing
a resource race leaves the run queued with a reason and no partial claims.
No SQL row lock remains open for the duration of a handler.

Global corpus/API resources need cross-tenant exclusion even though Jobs are
tenant-scoped. A restricted coordinator may compare private claims across
tenants; public results disclose only availability, never another tenant's
run or payload. Global resource definitions contain no tenant data. The
security and role design for this coordinator is part of migration review.

Fairness uses bounded base priority plus elapsed queue age with FIFO tie
breakers. A claim scan must look past blocked candidates to avoid blocking
an entire lane. Exact weights, capacities, and scan limits require synthetic
contention tests and measured connection/memory budgets before approval.

Dependency edges store the prerequisite run, scope, required input/material
revision, output contract, and failure rule. Completion publishes revisions
only after required writes succeed. Claim rechecks freshness; if newer inputs
invalidate it, wait for an appropriate successor rather than evaluate stale
or partial state. Graph construction rejects cycles and cross-tenant edges.
Parent workflows that only wait hold no worker slot or resource claim.

The initial edge families are the plan's graph: collection → applicable
client/identity resolution → required projector → scoped evaluator; Ninja
patches → patch classification → platform evaluation; software batches →
incremental classification; changed intelligence → coalesced full
classification. Platform evaluation does not send notifications inline.
Policy freshness and participant coverage remain additional dispatch guards.
Each actual edge still needs a named revision producer in the WP0 audit;
wall-clock proximity of two successful runs is not a revision contract.

## Proposal D: execution, timeout, and recovery

Run dedicated lane supervisors using the ingest image and a worker entrypoint
that does not start HTTP, schedules, migrations, or Metabase bootstrap. Each
supervisor launches one bounded child at a time. Children initialize their
own database clients; they never inherit live pooled connections. Supervisors
retain a separate bounded control connection for heartbeats and transitions.

Keep worker liveness, child liveness, meaningful progress, and wall-clock
deadline separate. A fresh heartbeat never extends an absolute execution
deadline. Progress only records real stage boundaries and honest counts.
The worker reports cancellation requests at reviewed safe checkpoints.

At timeout, record Needs attention and contain resources. A handler may be
terminated after its reviewed grace period only if its definition's kill-safe
claim has direct tests for interrupted writes and external effects. No
existing handler receives that designation by default. An unsafe or
unverifiably live child keeps its resource claims; lease expiry alone cannot
release them or authorize another execution.

Database claim tokens fence ledger transitions only. They do not stop stale
domain writes or undo a remote API call. Safe recovery therefore also requires
proof the prior child and relevant DB work have ended, or domain writers that
enforce the claim generation. Supervisor loss and container termination must
be tested, including the platform's forced stop behavior. If proof is absent,
the run remains contained for reviewed recovery. New disjoint work can still
claim other capacity; globally conflicting work must visibly wait.

Retry defaults to disallowed until the handler audit establishes idempotency
and a replay boundary. Notifications and source actions additionally retain
delivery/action attempt identities and before-send intent. If a vendor cannot
deduplicate or prove whether a lost response represents success, record an
uncertain outcome and require reconciliation. Local deduplication does not
justify promising exactly-once delivery.

Recovery and health work get Jobs records but cannot depend on obtaining a
resource held by the very run they inspect. Their control connections and
capacity are reserved and their duties limited to observation and verified
transitions. The scheduler's liveness is a service health signal; normal
maintenance runs remain in the ledger. Avoid infinite jobs-about-jobs chains.

## Proposal E: domain links and operator completion

Source-demand records and all three software queues retain their payloads and
history. Every newly executed domain item receives a same-tenant Job link
before work starts. A batch drain records each execution attempt's domain
membership so per-item failures are not hidden by a successful drain wrapper.
One source-action record can have several reviewed attempts: use a link per
attempt, not a repeatedly overwritten FK that loses earlier executions.

A proposed workflow root represents the operator's requested refresh.
Collection, resolution, projector, and evaluator children have separate
results and events. The root becomes Completed only after its required
children complete; waiting roots consume no execution capacity. Failure of
optional work remains an explicit warning with its own result. This changes
some existing nonfatal-wrapper semantics and requires acceptance.

Existing Jobs URLs, source/software demand forms, and diagnostic history stay
readable. Convert execution endpoints to admission adapters with the same
authorization as the UI. Status GETs remain reads; legacy GETs that mutate
must render a confirmation form and submit through authenticated POST with
appropriate CSRF protection. Audit callers before choosing redirects or
response changes. Infrastructure bootstrap is not an operator Run now job.

Normal users see Queued, Running, Completed, Needs attention, Cancelled,
Disabled, or Waiting for a named prerequisite/resource. Error payloads,
correlation details, and diagnostics remain behind admin permissions. API and
export permissions match UI permissions. New stable read views explicitly
revoke all inherited write privileges.

## Accepted rollout decisions

The user approved these three recommendations with "go" after reviewing the
recommendation summary. This accepts design direction only, not migrations,
runtime changes, deployment, or numeric capacity settings.

1. **Tenant rollout:** retain the current tenant-1 execution boundary while
   enforcing RLS on new Jobs paths. Reject unsupported tenants explicitly and
   require verified ownership for
   legacy domain links rather than guessing or bulk stamping old rows.
2. **Completion semantics:** use the workflow-root rule above, including
   visible failure when a required resolver/projector/evaluator fails,
   with required consumers identified before cutover.
3. **Recovery and rollout:** use a planned quiescence window for cutover,
   and manual reconciliation of uncertain external work with no automatic
   retry or forced kill for unaudited handlers. Automatic
   rolling coexistence with old direct-thread executors cannot enforce the
   new exclusive resource contract.

Numeric capacities, child memory limits, grace periods, and per-handler
deadlines remain unselected. Successful-run percentiles and a local pool
default cannot justify them. These parameters, missing inventory contracts,
exact migrations, role tests, and rollback rehearsal are prerequisites to
step 1.2 approval. This draft does not declare that gate passed.
