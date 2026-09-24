# ADR-0024 migration and rollout design

Status: Proposed; SQL migrations not written, approved, or applied

Companion to [ADR-0024](0024-unified-jobs-execution-contract.md). This is a
review specification, not executable migration SQL. The identifiers below are
proposed names; final migration filenames follow the then-current graph.
Current Operations migrations end at 0182. Do not reserve numbers by adding
empty migrations or alter historical migration files.

## Scope and sequencing

Use the Operations migration chain for Jobs-owned schema and cross-schema
links, after verifying its owner can alter the affected legacy tables. Do not
introduce a second migration runner for the same objects. Ingest SQL migration
dependencies, including software queue tables, must exist before linking them.
Both services wait for the required schema and definition revisions before
admitting or claiming converted work.

The following are logical changes for review. Their final grouping into files
depends on PostgreSQL lock/rewrite costs and the approved cutover. Separate
additive preparation from enforcement and activation. No step deletes history
or invents a successful run, historical payload, dependency, or source link.

## M1: definition snapshots and schedules

Proposed `operations.job_definition_versions` columns: definition key,
definition digest, handler version, JSON metadata, creation time. The primary
key is `(definition_key, definition_digest)`; metadata contains no tenant,
request, credential, source-instance, or customer values. Require object JSON,
bounded size, and an immutable-row trigger. Only the approved reconciler may
insert validated snapshots; neither runtime role may update or delete them.

Proposed `operations.job_schedules` columns: UUID, tenant, definition key and
digest, normalized scope identity, enabled, capability reason, cadence JSON,
anchor, time zone, next due time, last consumed due time, last requested time,
last request/run/outcome references, and configuration revision. Use a
same-tenant unique key on `(tenant_id, definition_key, scope_identity)`.
Definition references are composite; run references are tenant-composite.

Add tenant RLS and a due-time partial index for enabled schedules. Persist
schedule decisions and coalesced/missed tick counts in a tenant-scoped journal;
skipped ticks with no Job must still have durable explanations. Schedule
history must not fabricate Job completion. The active configuration revision
is checked under a row lock during every scheduling request.

Fresh installs need an explicit initial anchor policy. Existing cadence
history cannot be reconstructed from in-memory APScheduler state. Proposed
transition: record the approved activation instant and clearly label absent
historical schedule data. Initial catch-up behavior is reviewed per definition.

## M2: run contract and request identities

Extend `operations.operator_job_runs` additively with nullable historical
fields: definition digest, trigger, typed scope references, bounded request
JSON, request/coalescing identities, correlation ID, parent/root/retry-of run
IDs, wait category and reason, required/input/output revisions, structured
result and terminal reason, cancellation requester/time/reason, deadline,
worker incarnation, claim token/generation, and child-start metadata.

Add a contract version that distinguishes legacy from converted rows. New
admission requires the complete converted contract; historical rows retain
their recorded facts and unknowns. An insert default must not falsely stamp
an old writer's row as converted. Definition/scope/input fields become
immutable after admission, enforced by a trigger and the transition API.

Add `UNIQUE (tenant_id, id)` to support same-tenant self-references, events,
dependencies, resources, request aliases, and domain links. Scope and user
references must also prove tenant agreement; a plain UUID FK does not do so.
For existing rows, first measure violations and stop on contradictions rather
than silently rewrite ownership. Nullable historical parents remain unknown.

Proposed `operations.job_requests` is the idempotency ledger: tenant,
definition digest, request identity, normalized scope, admitted run reference,
actor, trigger, requested input revision, and request timestamp. Its unique
identity survives the run becoming terminal, making response-loss retries
safe. Coalescing multiple requests onto one run preserves each request alias.
Do not use a single overwritten `idempotency_key` on the run for all aliases.

The current unique `(tenant, job_key)` active index prevents distinct scopes
of the same definition running independently. Retain it during preparation;
replace it at the fenced cutover with an approved unique active coalescing
key. That is a compatibility change, not merely another nullable column.
All coalescing, alias, supersession, run, and initial-event writes commit
together. Test failed admission by checking that none of those records remain.

Keep existing status strings and URLs. Queued work can have a dependency wait
reason; `stalled` is a terminal outcome, not permission to release resources.
Lifecycle triggers validate transition preconditions and prevent overwriting
a terminal result. Retry creates a new linked attempt. Record cancellation
of queued work only if its claim did not win the same transaction race.

## M3: resources, execution ownership, and dependencies

Proposed tables:

| Table | Required contract |
| --- | --- |
| `job_workers` | Tenant, worker incarnation UUID, lane, process-start identity, definition version, liveness and readiness; registration cannot adopt another incarnation's child |
| `job_lane_limits` | Tenant/lane key, capacity, reviewed revision; claims serialize capacity changes with admission |
| `job_resource_definitions` | Immutable resource family, units and scope-conflict rule; global definitions contain no tenant-owned values |
| `job_resource_claims` | Tenant, resource identity and scope, units, owning run and claim generation, held/contained/released state, acquired/released timestamps and reason |
| `job_dependencies` | Tenant, dependent and prerequisite run FKs, required scope/input revision/output contract, edge state and failure reason |

Each claim's `(tenant_id, run_id)` FK references the existing ledger's
composite key. Held and contained claims both count against conflicting
admission. Terminal status on the run does not imply released claims.
Record an event for every transition. The resource identity distinguishes
tenant-local resources from genuinely global resources such as shared corpora.

Coordinator rows serialize overlap checks and claim accounting. Acquire
global resource coordinators, tenant resource coordinators, lane rows, and
run rows in one documented stable order for every multi-row operation. Scope
overlap is a defined hierarchy comparison, not just string equality. Claims
must be all-or-none. The claim token fences progress and finalization; child
termination proof or fenced domain writes are separately required for safe
recovery, as ADR-0024 explains.

Cross-tenant global-resource checks cannot rely on an ordinary tenant's RLS
view of the claims. Proposed mechanism: a dedicated NOLOGIN, NOSUPERUSER
coordinator role with narrowly scoped policies and API functions; callers
receive availability only. Do not use an unrestricted migration/superuser
function owner. Explicitly review the privileged function's tenant-context
checks, fixed search path, object qualifications, and execute grants.

Dependency insertion rejects self-edges and cycles under the same graph
mutation lock used by all edge writers. Composite FKs enforce same-tenant
references. Release rechecks required revisions and prerequisite outcomes.
Waiting workflow roots own neither an execution slot nor child resources.
Resource and dependency acquisition must not produce a cycle of waiting jobs.

## M4: journal and domain queue links

Preserve `operator_job_events` history. Strengthen the Job reference to a
tenant-composite FK after checking existing rows. Replace parent cascade
deletion with restricted deletion and protect journal UPDATE, DELETE, and
TRUNCATE through explicit grants and triggers. Sequence permissions must be
reviewed as well as table permissions. Add typed event/result payloads without
replacing old event text or claiming it contains telemetry never recorded.

Link new source-demand and source-action executions and all three software
queues. A source-action request may have multiple reviewed attempts, so use
an attempt/link relation with a unique run reference and retained attempt
number. Software batch membership must preserve the result of every executed
domain item. Nullable direct FKs alone cannot retain retries and batch history.

Migration 0020 source demand and the software queues have no proven tenant
ownership column. Do not add a default of 1 to historical rows merely because
current handlers hardcode tenant 1. Choose the initial tenant boundary in
ADR-0024 first. Then verify ownership, add nullable ownership, backfill only
proved rows, and enforce non-null ownership and same-tenant links for newly
executed records. Unattributed historical rows stay retained under an explicitly
restricted legacy administrative read path; they cannot be claimed or exposed
as ordinary tenant history. A missing ownership mapping blocks execution.

Source-action migration 0160 also needs explicit RLS, same-tenant finding/
source/user references, and protected attempt writes. Review other migrations
and live grants before treating the migration's initial grants as deployed
state. Do not revoke legacy readers during additive preparation without the
corresponding read adapters ready for cutover.

Queue status fields remain for compatibility but are projections of the Job
outcome for converted rows. Only the transition API can update both. Legacy
reapers must ignore converted work; all direct thread starts and manual queue
claim paths are disabled before the new worker activates that family.

## M5: enforcement, read models, and roles

Replace raw runtime INSERT/UPDATE on converted Jobs state with constrained
request, claim, stage, cancel, finish, and recovery APIs. These can be SQL
functions called by shared adapters, but require explicit, tested ownership
and privileges. A Python helper alone does not prevent raw-row callers.
Operations may request permitted work and read authorized projections;
ingest may claim/execute registered work. Neither gets arbitrary ledger DML.

Every new tenant table has ENABLE and FORCE RLS, a context-bound USING and
WITH CHECK policy, tenant-composite relationships, and indexes whose leading
tenant keys match the access paths. Missing tenant context must fail closed.
Tenant policy is not client authorization: request adapters still validate
client membership, scoped permission, and referenced objects for the actor.

Views must preserve the RLS boundary through the approved PostgreSQL mechanism
and have explicit tenant filtering where needed. Verify the deployed
PostgreSQL version before selecting view options. Revoke inherited INSERT,
UPDATE, DELETE, and TRUNCATE from all runtime/reporting roles; granting SELECT
alone does not remove default write privileges. Separate ordinary sanitized
results from administrator diagnostic storage/projections.

Use a privilege matrix in the executable migration review: table/sequence/
function, owner, permitted operations, tenant policy, and caller role. Include
PUBLIC, `operations_app`, `ninja_ingest`, `operations_readonly`, and
`metabase_ro`. Verify default privileges and role memberships with read-only
checks before proposing production enforcement.

## M6: worker topology, activation, and rollback

Proposed Compose topology: keep ingest as HTTP plus schedule producer; add
lane worker services built from the same ingest Dockerfile. Each worker has
one supervisor and at most one child. Reuse packaged `shared/` metadata and
ingest runtime files. Worker health uses its own bounded liveness/readiness
check; override the image's existing HTTP healthcheck, because a worker does
not serve ingest HTTP. No public worker port is needed.

Set a deployment-wide connection budget before deciding how many lane services
can run together. Account for supervisor control connections, child pools,
HTTP/scheduler connections, Django, Metabase, and maintenance headroom. Five
copies of today's four-connection ingest pool are not equivalent to the
current two-thread ceiling. Define CPU/memory/termination settings only after
that budget is reviewed. Docker stop may force-kill a child independently of
the Jobs kill-safe flag; deploy procedures must drain or contain first.

The current Operations entrypoint applies migrations at startup. The current
ingest entrypoint starts its own schedules/direct-thread catch-ups, and its
old claim query does not filter by contract version. Merely starting new
workers beside the old process can double-execute converted work.

Proposed rollout, pending the user's acceptance of a quiescence window:

1. Prepare additive schema and compatibility code with converted admission
   disabled. Review the exact pending ingest and Django migration sets.
2. Quiesce producers and old executors through the approved rollout mechanism.
   Confirm domain threads and external attempts have completed or are retained
   for manual reconciliation. A terminal Job row alone is insufficient proof.
3. Preserve old pending/history rows. Drain or explicitly adopt pending work
   only under a reviewed per-family procedure; do not fabricate old payloads.
4. Fence raw writers, activate the agreed definition/schema revision, then
   start compatible producers and workers. Readiness refuses version mismatch.
5. Reconcile the ledger, domain links, schedule state, and operator surfaces
   with a small read-only smoke check. Retain old read compatibility through
   the approved observation period.

Before converted admission, rollback can retain additive tables and use
compatible prior code. After converted work exists, rollback must first
quiesce the new executors and reconcile uncertain actions; reinstalling the
old image directly is unsafe because its broad claims ignore new ownership.
Retain ledger, aliases, events, attempts, and domain links. No DROP/TRUNCATE
rollback is proposed. A forward repair may be safer; production rollback and
manual data changes require their own approval.

## Review exit and proportional validation

This document has source-level review only. No PostgreSQL migration was run.
Keep validation focused, following the user's request to avoid heavy testing:
verify the actual transition/grant/FK behavior with small synthetic examples
when executable migrations exist, plus targeted claim contention, stale-owner,
uncertain-send, and cancellation checks when those mechanisms are implemented.
These are safety properties, not a request for a broad new test framework.

Before step 1.2 approval, provide executable SQL, the full handler inventory,
tenant rollout decision, numeric process/connection budget, ownership and grant
checks, migration lock/backfill analysis, and a concrete rollback procedure.
The architecture draft and this specification alone do not satisfy that gate.
