# Operations architecture

This document is the concise guide to Operations architecture. During the
documentation transition, `../DESIGN.md` remains the detailed architecture
authority. `../BLUEPRINT.md` contains mixed implemented and pending planning
material and must not override DESIGN or implemented behavior without review.

## Guiding principles

1. Operations is source-agnostic; Ninja is one source.
2. Source observations remain individually visible and auditable.
3. Identity resolution is a platform capability, not connector logic.
4. Canonical entities are durable; derived current state is rebuildable.
5. Findings state facts; policies and notification rules state responses.
6. Operator decisions are not source fields and must survive refresh.
7. Per-domain storage is separated into canonical/configuration, derived,
   operator-decision, and effective-read layers.
8. Tenant scope and RLS are architectural boundaries.

## Data layers

```text
Source connectors
    │
    ▼
source-branded raw schemas
    │ normalized current-state writes
    ├── entity_observation_current + entity_observation_history
    └── software_installations_current + software_installation_history
    │ identity/client resolution
    ▼
canonical clients/devices and source links
    │ domain refresh
    ├── derived current/materialized state
    ├── operator decisions and overrides
    ▼
effective views (for example operations.v_device)
    │
    ├── evaluator and findings
    ├── notification dispatcher
    └── Django views and APIs
```

### Canonical

Canonical tables identify real-world entities and maintain lifecycle and audit
metadata. They are not automatically deleted due to source absence.

### Derived

Derived tables and materialized views summarize observations and domain logic.
They are safe to recompute through documented refresh functions and dependency
order.

### Observation state and history

Generic source state is stored once per source-scoped identity in
`entity_observation_current`; `entity_observation_history` records only
material and presence changes as SCD-2 intervals. Software installations are
a high-cardinality device-to-product relationship inventory and use the
dedicated `software_installations_current` and
`software_installation_history` tables. The retired
`entity_observations` table is an empty compatibility shell, not a runtime
reader or writer target.

### Operator decisions

Operator choices such as exemptions, overrides, suppressions, mappings, and
software decisions are stored separately and audited.

### Effective views

Consumers read effective views that combine canonical facts, current derived
state, and operator decisions. Consumers should not reproduce domain precedence
logic independently.

## Identity resolution

Resolution uses client/tenant scope and explainable match evidence such as
quality-controlled serials, VM identifiers, and strict normalized hostnames.
Ambiguous or cross-client cases become candidates/findings.

Source links retain:

- Source and external identifier
- Entity/observation type
- Match method and confidence
- Source-specific evidence

One canonical entity may have multiple links, including multiple records from
the same source.

## Client resolution

Client/source-group mapping follows an explicit ladder:

1. Existing source identifier link
2. Approved alias or exact normalized-name match
3. Collision/conflict finding
4. Candidate for operator accept, map, exclude, or fix

Requirement profiles provide reusable coverage policy. Client-scoped coverage
requirements are sparse overrides: an enabled row explicitly requires a
service, a disabled row explicitly exempts it, and no row inherits the
assigned profile (or the tenant-global fallback when no profile is assigned).

## Queues

Queues use registered contracts for:

- Pending/processing/completed/failed state
- Leasing and stale recovery
- Retry policy
- Depth and age health
- Audit/run visibility

Interactive demand queues and background queues may use different stale-entry
behavior, but both must be governed and observable.

## Findings

Finding evaluation reads effective state and emits deduplicated conditions with
severity, confidence, subject, condition key, evidence, and lifecycle.

Findings do not directly send notifications. The notification layer applies
suppression, rule matching, cooldown, routing, and event audit.

## Patching layer

Patching scope is domain-specific:

- Derived scope combines source signals, defaults, and policy allowlists.
- Typed operator overrides provide Included/Excluded decisions.
- `v_device` exposes effective patching scope and current session state.
- Patch findings use canonical patch signals and effective scope.

## Security and RLS

- Runtime access uses a restricted role.
- Tenant context must be established before tenant-scoped ORM work.
- Migration/bootstrap roles are separate.
- Materialized views cannot receive PostgreSQL RLS directly; effective scoping
  must be provided through controlled joins/views and trusted-role boundaries.

## Legacy transition

Legacy agent-compliance code and schema remain until:

- Native source observation and identity paths are complete.
- Evaluator, findings, notifications, and UI parity are verified.
- Metabase and other consumers are audited.
- Destructive retirement is separately approved with backup and rollback.
