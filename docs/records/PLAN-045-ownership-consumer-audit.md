# PLAN-045 ownership consumer and writer audit

Status: In progress, 2026-11-03. This is a code and local schema audit, not a
production assessment or a complete consumer inventory. It contains no live
data. PLAN-045 and ADR-0052 own the scope and proposed contract.

## Confirmed writers and concurrency

| Path | Behavior | Transition requirement |
| --- | --- | --- |
| `ingest/observations.py` | Upserts observations and can update `client_id`; preserves an existing value when the incoming value is null. | Invalidate both old and new Computer ownership on a relevant change, including activity changes. Do not treat every null input as a clearing event. |
| `ingest/identity/client_resolver.py::_attach_group` | Fills null observation clients for an attached source group. | Fence and enqueue affected Computers even without a new association. |
| Migration 0374 `set_source_association` | Locks the source subject and link and changes the observation's `device_id`; it does not lock the target Computer. | Fence and enqueue both the former and new Computer, including detach and concurrent attach. |
| Migration 0374 `move_client_source_group_v1` | Updates observation clients and can call the operator Computer move. | Replace its source-derived Computer write with the shared projector protocol; retain the operator's source-mapping decision and audit. |
| Migration 0340 `accept_computer_client_conflict` | Writes accepted evidence keys; does not lock the Computer or record a chosen client and evidence-client snapshot. | Preserve existing decisions without promoting keys to an indefinite ownership override; fence decision updates. |
| Migration 0340 `move_computer_to_client` | Locks and moves the Computer and scoped dependents; attributes the action to an operator. | Keep human actions distinct from the source-derived writer. Audit existing action history and define how subsequent contradictory evidence is handled. |

An observation trigger must cover inserts, updates, deletes, and both old and
new device IDs where applicable. Lock ordering, transaction isolation, and queue
acknowledgment still require a concrete design and concurrent PostgreSQL tests;
a dirty flag alone is not proof that readers cannot see stale ownership.
On the local schema, the observation admission trigger already fires for
`client_id`, `device_id`, activity and material-hash changes, but it enqueues
source-record work, not a verified Computer-ownership projection. The local
decision triggers validate and audit decisions; no ownership enqueue trigger
was present. Confirm the deployed migration chain before relying on either.
Migration 0370's tenant input generation advances through a deferred trigger
on inserted or updated source subjects. That mechanism alone does not certify
an ownership projection against operator-decision changes or observation
deletes; any reuse needs explicit coverage and commit-order tests.

## Confirmed consumers and dependent copies

| Surface | Evidence and implication |
| --- | --- |
| Tenant boundary | Local PostgreSQL catalog shows tenant-only RLS on devices, entities, observations, findings, software decisions and current installations. `TenantMiddleware` sets the tenant; `ClientScopeMiddleware` resolves a URL client but does not enforce client filtering. |
| Client Computer list | `org_devices` filters `Device.client` directly. Existing stored IDs cannot remain authoritative for unresolved Computers. |
| Device and entity views | Local view definitions for `v_device`, `v_entity_admin_summary` and `v_device_software_exposure` reference Computers and client values. Audit each caller and grants. |
| Materialized presence | `device_agent_presence_current` and `device_session_current` materialize `devices.client_id`; both are consumed by Operations and ingest. A resolved move or unresolved transition can leave stale client results after a successful transaction until refresh. Refresh-only protection leaves an unsafe interval; include a current-ownership fence at consumption or an equivalent atomic mechanism. |
| Source-record inventory | `v_computer_inventory_source_record_current` uses the observation's own client. Source-record attribution and Computer ownership are different contracts; do not replace source client evidence indiscriminately. |
| Scoped dependents | The move function updates entity and OS copies, findings, current software installations, device-scoped software decisions, Windows servicing and name collisions. `device_requirement_state` and `software_inventory_devices` have a device ID but no client ID and must be traced through joins and computations. |
| History | `software_installation_history` stores a required client and device. It is a history store, not listed in the move function. Determine access semantics for old history separately; do not rewrite historical ownership blindly. |
| Move provenance | The source-group procedure calls `move_computer_to_client`, which records `computer.move_client` as an operator action using the same procedure as a direct human move. An action name alone therefore cannot reliably distinguish an explicit Computer ownership choice from an automatic consequence of a group move. |
| Software decisions | Some matching queries use `client_id IS NULL` as a broad scope. Preserve the device dimension and audit each matching query before considering nullable decision client values. |

The local catalog also lists materialized `device_patching_scope_current` and
views `v_computer_os_installation_current` and `v_device_last_user_current`
that reference devices without necessarily carrying a client. Their downstream
joins and write paths are not yet audited. Direct ORM, raw SQL, exports,
notifications, APIs, queues and less obvious relationship paths also remain.

## Verification and remaining work

Catalog inspection was read-only against the running local development
database. It checked schema metadata, selected policies and view definitions;
its recorded latest Operations migration is 0391, while the repository has
0400. The catalog results therefore describe the local schema at 0391, not the
current repository schema or production. Reconcile the nine intervening
migrations before relying on them for implementation or local validation.
Local table-level grants allow `ninja_ingest` to update devices but not entities,
software decisions or current software installations; check column-level and
function privileges as well before designing the projector grants. The local
`operations_app` has table-level UPDATE on `device_session_current`; that
materialized view is not an ordinary updatable table, but the privilege still
needs explicit review when replacing or wrapping it.
Finish the inventory and privilege audit, choose the representation and
concurrency protocol, then prove isolation, materialized-read freshness,
decision semantics, dependent moves and retry behavior with synthetic cases.
