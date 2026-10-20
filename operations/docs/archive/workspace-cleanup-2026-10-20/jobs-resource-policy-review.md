# Jobs resource and fairness policy review

Status: approved by the user on 2026-09-24. Migration 0185 implements the
additive claim/dependency primitives; no runtime producer or existing
version-0 Job has been converted or activated through them.

## Why this review exists

Step 2.3 requires concrete capacity, resource, fairness, dependency, and
supersession policy. Those values were not closed during Step 1.1/1.2:
production measurement remained partial, the registry intentionally retained
empty `resource_keys`, and the topology review selected no process or
connection budget. Implementing Step 2.3 without this review would therefore
invent production concurrency behavior.

This proposal is deliberately conservative. It preserves the two limits that
source inspection actually proves today:

- at most two durable handlers execute through the process-local semaphore;
- each of the five lane pollers has `max_instances=1`.

It does not certify handler retryability, kill safety, scope independence, or
complete transitive write sets. Those remain per-family activation gates.

## Proposed initial capacities

| Coordinator | Capacity | Evidence and effect |
| --- | ---: | --- |
| Deployment execution pool | 2 | Preserves the current `BoundedSemaphore(2)` ceiling across the future deployment-wide coordinator. |
| `collection` lane | 1 | Preserves one active poller for the lane. |
| `evaluation` lane | 1 | Preserves one active poller for the lane. |
| `software` lane | 1 | Preserves one active poller and existing classifier exclusion. |
| `intelligence` lane | 1 | Preserves one active poller and serial global-corpus work. |
| `service` lane | 1 | Preserves one active poller for notification/maintenance work. |

Every claim consumes one deployment execution unit and one unit from its lane.
No lane may borrow around the deployment total. Control-plane work such as
leadership, heartbeats, and recovery consumes neither execution nor lane
capacity unless it starts a handler.

Changing these numbers requires measured database/API/process capacity and a
separate reviewed policy revision. Step 3.1 may implement fewer workers than
these maxima; it may not silently increase them.

## Proposed initial resources

All resources below are exclusive, one-unit resources. Registry metadata uses
templates; runtime code materializes the tenant ID and never stores customer
names, source identifiers, or credentials in global definition snapshots.

| Resource | Initial definitions | Reason |
| --- | --- | --- |
| `tenant:{tenant_id}:state` | Every definition except the seven global-only definitions listed below | The audit does not yet prove independent tenant write scopes. Broad exclusion is the safe baseline. |
| `global:intel-cve-corpus` | `intel-nvd`, `intel-cpe-dict`, `intel-kev`, `intel-epss`, `intel-matcher` | These definitions write or consume the shared CVE/CPE corpus. |
| `global:software-catalog` | `software-classify`, `software-classify-only`, `software-classify-full`, `intel-winget`, `intel-chocolatey`, `intel-capability`, `intel-lolrmm`, `intel-category`, `intel-endoflife` | These definitions write or consume shared package, category, capability, lifecycle, or safety intelligence. |
| `tenant:{tenant_id}:software-inventory` | `software-enqueue-orgs`, `software-queue-drain`, `software-classify`, `software-classify-only`, `software-classify-full` | Inventory production and classification currently lack a proved material-revision boundary. |
| `tenant:{tenant_id}:notification-delivery` | `notifications-dispatch`, `notifications-digest` | External delivery and its durable evidence must not overlap until route-level idempotency exists. |
| `tenant:{tenant_id}:legacy-agent-compliance` | `agent-compliance`, `agent-compliance-evaluate` | Preserves the existing legacy bridge exclusion. |

The seven initial global-only definitions are `intel-nvd`, `intel-cpe-dict`,
`intel-kev`, `intel-epss`, `intel-capability`, `intel-lolrmm`, and
`intel-category`. Every other current registry definition claims
`tenant:{tenant_id}:state`. Definitions that appear in multiple rows must
atomically acquire every listed resource or acquire none.

This baseline permits one global-only intelligence handler to run alongside
one tenant-state handler, subject to lane limits and the deployment total. It
does not assert that narrower tenant/client/source concurrency is unsafe; it
defers that expansion until a family's writes and external limits are proved.

## Proposed priority and aging policy

- Preserve the current base priority of 50 for every existing definition.
- Effective priority is
  `min(100, base_priority + floor(queued_seconds / 300))`.
- Order by effective priority descending, then original request time and UUID
  ascending.
- Aging affects claim order only. It never bypasses dependencies, resources,
  lane capacity, capability gates, or containment.
- No current definition receives a higher base priority in this package.

With the existing equal priorities, this preserves oldest-first behavior.
If later work introduces higher priorities, a continuously waiting ordinary
Job reaches the cap after 250 minutes and wins ties by its older request time.

## Proposed dependency boundary for Step 2.3

Step 2.3 implements and tests the generic dependency mechanism but activates
no production dependency edge. Step 5.1 remains responsible for the full
family graph and its material revision producers.

The generic contract is:

- every edge names an exact required scope, input revision, output contract,
  and failure rule; missing revision data is invalid rather than "fresh";
- self-edges, cross-tenant edges, and cycles are rejected under the graph
  mutation lock;
- a required prerequisite releases its dependent only after `completed` and
  after publishing the required output revision;
- failed, stalled, or cancelled prerequisites leave dependents visibly
  blocked; they do not silently run against stale state;
- workflow roots complete only after all required children, as already
  approved; waiting roots hold no lane slot or resource claim.

Synthetic definitions may exercise the engine in focused tests. They do not
authorize a production edge or certify any existing handler result.

## Proposed supersession policy

Only the already implemented Software classifier family receives cross-key
supersession in Step 2.3:

| Definition | Breadth |
| --- | ---: |
| `software-classify-only` | 1 |
| `software-classify-full` | 2 |
| `software-classify` | 3 |

- An active equal-or-broader request coalesces a narrower request.
- A newly admitted broader request cancels queued narrower work and retains a
  supersession event/request alias.
- Running work is never cancelled by supersession. A broader request becomes
  a queued successor and waits for the shared resources.
- Every other definition uses exact-definition/scope coalescing only.

This is a direct preservation of the current Software priority ordering; it
does not introduce a new family policy.

## Enforcement and rollout boundary

The Step 2.3 migration/API may create coordinators, claims, dependencies, and
policy revisions and test them with synthetic rows. Existing version-0 writers
remain compatibility paths until their family conversion. No production Job
definition is converted merely by adding schema or registry metadata.

Activation requires all-or-none claims using the ADR-0024 lock order:
global resource coordinators, tenant resource coordinators, lane coordinator,
then candidate run. A failed claim leaves no partial resources. Contained
resources are not released merely because a run is marked terminal.

## Approved scope

Approval of this package accepts only:

1. deployment capacity 2 and per-lane capacity 1 as the initial ceiling;
2. the broad resource mapping above as a conservative activation baseline;
3. five-minute/100-cap priority aging;
4. generic dependency machinery with no production edges until Step 5.1;
5. the existing Software-only cross-key supersession order.

It does not approve migration execution, production activation, deployment,
worker counts, connection budgets, family conversion, automatic retry, forced
termination, or broader concurrency.
