# 0027 — Jobs product and execution model

Status: Accepted
Date: 2026-10-06

## Decision

Jobs uses one model independent of the current implementation:

```text
Job -> Run -> Stage
```

A Job is one repeatable task with one meaningful result. A Run is one attempt
to execute it. A Stage reports progress inside a Run. Jobs may require valid
results from other Jobs, but there is no separate workflow, operation, or
administrator-facing execution-entry model.

The scheduler, dispatcher, workers, recovery monitor, and health checks are
System services. They operate Jobs and never appear as Jobs themselves.

ADR-0024 and ADR-0026 remain authoritative where they provide stricter
durability, fencing, isolation, capacity, data-safety, and RLS guarantees.
This record supersedes their operator terminology and organization model.

`shared/jobs_registry.py` is the sole catalog authority for Jobs. It declares
every executable definition, handler identity, lifecycle contract, scheduling
policy, prerequisite, capacity boundary, data lock, and operator presentation.
The scheduler, worker, and user interface consume that catalog; none retains a
second list of Job keys. Discovery tests may inspect code for unregistered
execution paths, but an inventory report is evidence, never another catalog.

## Job boundary

Create a separate Job only when the task has an independently useful result,
trigger, schedule, status, failure, retry, or manual control. Multiple function
calls do not create multiple Jobs. A Stage becomes a Job only when it satisfies
that independence rule.

Consequences:

- one source refresh may have several collection and projection Stages;
- independently scheduled feeds remain independent Jobs;
- incremental and full processing may be modes of one Job when they share the
  same result and controls;
- queue polling, request dispatch, recovery, and worker loops remain System
  services; and
- a client/source/device selection is Run scope, not a new Job.

Configured sources share the `source-refresh` Job definition, but each binding
has its own schedule, Run scope, result, and safe control. Sources owns that
configuration and evidence; Jobs may show each current source-bound Run so an
operator can see and control all collection happening now. This is execution
presentation, not a separate definition for every source.

For example, `Refresh Hudu` is one source-bound Run of the internal
`source-refresh` definition. Operators see and control `Refresh Hudu`; they do
not see a second generic source-refresh Run alongside it.

## Durable model

The minimum durable model is:

| Record | Responsibility |
| --- | --- |
| Job definition | Stable key, name, handler, result contract, allowed scope, prerequisite rules, capacity requirements, data locks, timeout, retry/cancellation policy, and permissions |
| Tenant Job configuration | Enabled state and schedule for one tenant |
| Job Run | Tenant, Job, scope, trigger, state, reason, timestamps, result, error, and attention flag |
| Run prerequisite | Required Job/Run result and freshness condition |
| Run event | Append-only lifecycle and Stage evidence |
| Capacity claim | Execution capacity held by a running Run |
| Data lock | Protected data identity held by a running or contained Run |

There is no independent health or source-status authority. The current source
view is derived from source configuration and its scoped Runs. An actionable
Jobs, source, or service problem is represented through the existing Issue
mechanism. Dashboard, Jobs, Sources, and Admin Health project the same catalog,
source configuration, Run facts, and Issues at different levels of detail.

Executable handlers and safety constraints are code-owned. Tenant enablement,
schedules, and reviewed capacity limits are data. Every editable value has an
administrator surface and audit record; handlers, data locks, and retry safety
are not editable configuration.

## Run lifecycle

Every Run has exactly one state:

| State | Meaning |
| --- | --- |
| Waiting | A prerequisite, data lock, or capacity requirement prevents admission |
| Ready | The Run is eligible for a worker claim |
| Running | A worker owns a fenced claim and is executing the Run |
| Completed | The result contract was satisfied |
| Failed | The result contract was not satisfied or execution ended unsafely |
| Cancelled | The Run was stopped under its cancellation contract |

`Needs attention` is not a state. It is a flag on a Failed Run when an
administrator must retry, reconcile, or resolve it. `Disabled` is Job
configuration, not a Run state. `Not run yet` means no Run exists.

The Jobs list derives Latest status deterministically:

1. show the active Run when one exists;
2. otherwise show the most recent terminal Run;
3. otherwise show Not run yet; and
4. show configuration and attention separately.

Waiting has one durable cause and one plain explanation:

| Cause | Administrator explanation |
| --- | --- |
| Prerequisite | `Waiting for: <Job>.` |
| Required data | `Required data is still being updated.` |
| Data lock | `Another Job is updating the same data.` |
| Capacity | `The system is busy with this type of task.` |

The interface never repeats the same fact as status, Stage, and detail.

A completed source Run confirms its required collection contract. A projection
that is required to make collected records usable fails that Run; an optional
projection must have its own durable administrator health condition rather
than being only a runtime-log exception.

## Requests, scheduling, and prerequisites

Manual, scheduled, event-driven, and prerequisite-triggered requests use one
admission API. A schedule is an attribute of a Job. Run scope identifies the
tenant and optional client/source/device target.

Equivalent active requests coalesce by Job, tenant, scope, and relevant input.
A request with genuinely newer input may create one successor Run; it does not
create an unbounded duplicate queue.

A Job may require one or several Job results. The scheduler records those
requirements, their scope, and freshness condition. It admits the waiting Run
only after every required result is valid. The administrator interface says
`Waiting for` and `Starts after this`; it does not expose a workflow product.

## Capacity and data safety

Capacity and data safety are independent:

| Question | Enforcement |
| --- | --- |
| Is there room to execute this Run? | Execution-capacity pool claims |
| May this Run overlap with those already executing? | Data locks |

Each Job declares every capacity pool and data lock it requires. Admission
acquires all required claims atomically in stable order or acquires none.
Workers scan past temporarily blocked Runs so one Job cannot block unrelated
Jobs. Fair database-backed selection prevents one Job or tenant from
monopolizing a pool.

Only a small bounded number of Runs are Ready. Waiting Runs remain durable and
explainable but are not counted as queued/Ready. A deployment-wide process
ceiling is an emergency fuse, not ordinary scheduling policy.

Postgres owns admission, ordering, claims, capacity, and locks. Stateless
workers own only their local child processes, so no supervisor is a dispatch
bottleneck or durable authority.

## Interruption and recovery safety

Every worker claim has a token and generation. Completion, heartbeat,
cancellation, and failure updates require the current token, preventing an old
worker from changing a reassigned Run.

Running Jobs heartbeat and have a deadline. Cancellation is cooperative at
declared safe checkpoints. Forced termination is permitted only when the Job
is explicitly kill-safe. Otherwise an interrupted Run becomes Failed with
attention required, and its data locks remain contained until recovery proves
the prior execution cannot still mutate data.

Automatic retry is allowed only for a declared replay-safe Job. External
mutations and deliveries are never presumed replay-safe.

## Tenant safety

Tenant and scope are part of every Run, schedule, prerequisite, claim, lock,
result, and query. RLS applies from admission through presentation. Shared
global data uses explicit global locks without disclosing another tenant's Run
details. Capacity selection is fair across tenants.

## Administrator experience

### Jobs

The Jobs page is one compact row per Job:

```text
Job                  Latest status                               Schedule       Action
Refresh source data  Running - collecting current data           Every 4 hours  Request stop
Update patch status  Waiting for: Refresh source data             Automatic      Cancel
Update feed data     Completed - 1,204 updated at 09:00          Daily          Run now
Send alerts          Failed - needs attention at 08:30            Every 15 min   Retry
```

It provides search, status and scope filters, safe bulk actions, Refresh now,
Auto-refresh on/off, and a last-updated time. It has no category headings,
inline history expansion, technical identifiers, or separate Activity page.

### Job detail

One Job detail page provides Latest Run, current Stage, Waiting for, Starts
after this, permitted controls, paginated Run history, and collapsed technical
evidence. History belongs to the selected Job and never replaces Latest
status.

### Admin configuration

Admin > Job configuration provides enablement, schedules, reviewed execution
limits, and a complete coverage/diagnostic view. System services appear in
Admin Health. Nothing is hidden from an administrator merely because it is
absent from the normal Jobs list.

## Completion criteria

The Jobs ecosystem is complete when:

1. Every Job has one definition, list row, detail route, truthful Latest
   status, schedule summary, result, and allowed controls.
2. Every invocation creates or coalesces into a durable Run before execution.
3. Every active Run has one factual state and reason.
4. Prerequisites, capacity, and data locks are enforced independently and
   atomically.
5. Current status and immutable history remain distinct.
6. System services do not masquerade as Jobs but remain visible in Health.
7. Row, bulk, retry, cancellation, timeout, and recovery controls use the same
   permissions and safety contracts.
8. Tenant/RLS, fencing, audit, fairness, and coalescing guarantees are proven
   by focused tests.
