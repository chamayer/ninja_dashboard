# 0011 — Lifecycle evidence and immutable transition audit

Status: Accepted; activation release prepared
Date: 2026-07-31

## Context

Device identity, collector presence, direct agent contact, and reported
operating state answer different questions. The prior lifecycle evaluator used
identity-oriented classifications and collection presence as proxies for
contact. That allowed second-hand or powered-off evidence to keep a Device
active and gave new entity types implicit lifecycle authority.

Production aggregate measurement confirmed the distinction. `network.device`
and `monitor.target` records can report explicit online/offline state, while
hypervisor-reported VM power state is a valid power measurement but does not
prove guest-OS health. Direct agent contact is the higher-fidelity guest-OS
signal. The final preactivation projection contained 343 lifecycle transitions,
99 unknown present-null `vm.host` power states, no equal-time reported-state
conflicts, and 18 eligible devices without qualified evidence. No customer
identifiers or payload values were retained in the design record.

Automatic changes also require a durable explanation. Lifecycle transition
events belong in the generic Operations audit stream so the later unified
entity model can extend their subject references without moving or rewriting
their history.

## Options considered

- **Continue deriving lifecycle authority from identity classification or
  source presence.** Rejected because neither proves contact or operating
  state and new types would inherit unintended authority.
- **Use one `is_contact_evidence` boolean.** Rejected because direct contact
  and reported power/online state have different fidelity and interpretation.
- **Use an explicit evidence mode per entity type, with deterministic
  selection and fail-closed defaults.** Selected.
- **Make lifecycle policy runtime-editable immediately.** Rejected for this
  track. A wrong row can change production lifecycle state without code review;
  audited runtime editing requires a separate design.

## Decision

`operations.entity_types.lifecycle_evidence_mode` is the sole lifecycle
capability. Its allowed values are:

- `none`;
- `direct_contact`;
- `reported_state`; and
- `direct_then_reported_state`.

The non-null database default is `none`. Classification, identity authority,
license consumption, and coverage eligibility cannot substitute for this
capability.

Evidence selection follows these rules:

1. Direct agent contact is the highest-fidelity guest-OS liveness evidence.
2. Explicit hypervisor power state is authoritative for the VM power dimension
   and is valid lower-fidelity lifecycle evidence.
3. Explicit source-reported online/offline state is valid only when the state
   is recognized; collection time alone is not contact.
4. The newest qualified evidence wins. Direct contact wins an exact timestamp
   tie.
5. Powered-on/online evidence can support `active`; powered-off, suspended, or
   offline evidence can support `offline_aging`.
6. Missing evidence leaves lifecycle unchanged. Unknown states and equal-time
   reported-state conflicts leave lifecycle unchanged and create visible,
   auto-resolvable data-quality findings.

Automatic policy retains the deployed three-state lifecycle:
`active`, `offline_aging`, and `pending_cleanup`. `retired` is operator-owned
and automatic evaluation never changes it.

Every automatic transition updates the Device and inserts a
`lifecycle.transition` event into `operations.audit_log` in the same database
transaction. The event records the tenant-scoped Device identifier, policy and
selected-evidence metadata, and before/after lifecycle state without copying
raw source payloads or customer-facing values. If the audit insert fails, the
state update rolls back. Runtime roles may append permitted audit events but
cannot update or delete audit history.

The policy/status and transition history are read-only under
**Admin → System → Lifecycle policy**, protected by the shared Admin
authorization and tenant context.

Migration `0093` deliberately landed only the schema, constraints, finding
types, registry/audit grants, and read-only surface, with every entity type at
`none`. Activation migration `0094` requires that inert precondition and the
presence of all seven reviewed types, then applies the approved modes. The
activation is coupled to a fresh aggregate projection, verified restricted
backup, and one controlled reconciliation run. Collection, observations,
coverage, and other evaluator work remain unchanged.

## Rationale

An explicit mode preserves the higher fidelity of agent contact while keeping
valid power and reported-state measurements. Deny-by-default behavior makes a
new or unknown type unable to affect lifecycle accidentally. Atomic append-only
audit provides one durable account of automatic state changes. Landing policy
inert separates schema compatibility from production state reconciliation.

## Consequences

- Connectors must expose explicit state and measurement time; a successful poll
  alone is insufficient.
- Unknown/null/unmapped state is visible but cannot cause a transition.
- Registry policy remains deployment-controlled until an audited editing
  workflow is accepted.
- Schema landing temporarily pauses automatic lifecycle updates because the
  new evaluator replaces the legacy sync while every mode is `none`.
- The activation release requires its own aggregate measurement, backup,
  transition reconciliation, validation, and rollback gate.
- In the current GitOps deployment, approval to push the activation commit to
  `origin` must also approve the resulting Portainer redeploy and automatic
  startup migration. They cannot be represented as later independent gates.

## Supersedes or superseded by

This decision supersedes lifecycle semantics inferred from
`is_identity_signal` or source-record presence. It is compatible with
ADR-0005's typed Device layers and ADR-0007's content-hashed observation
history. It does not alter the separately tracked stable-source-identity or
unified-entity-ecosystem designs.
