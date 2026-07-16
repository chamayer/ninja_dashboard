# Operations requirements

## Purpose

Operations is the tenant-aware control plane for cross-source operational
inventory, identity, coverage, findings, decisions, notifications, and
workflows.

## Core requirements

### Canonical inventory

- Represent real clients, devices, and future entity types independently from
  any one source.
- Keep every relevant source record visible and auditable.
- Never automatically delete a canonical entity merely because a source stops
  reporting it.
- Distinguish physical form, source presence, lifecycle, and operator policy.

### Observation and identity

- All connectors write source observations with source identity and timestamps.
- Resolve observations to canonical entities using explainable match methods
  and tenant/client boundaries.
- Preserve ambiguous cases for review instead of silently merging them.
- Support multiple records from the same source when they represent distinct
  observations of the same entity.
- Promote unmatched observable entities so inventory gaps are visible.

### Coverage and findings

- Define coverage requirements by entity type, platform, device scope, and
  client/profile policy.
- Evaluate missing, stale, offline, lifecycle, identity, source, software, and
  patching conditions from effective current state.
- Separate facts from notification policy: findings describe conditions;
  notification rules decide responses.
- Deduplicate finding instances and retain lifecycle/audit history.
- Support acknowledgements, suppressions, and operator review.

### Operator decisions

- Store operator decisions separately from source-derived and canonical data.
- Validate decision values against their domain rules.
- Preserve decisions across source refreshes and derived-state rebuilds.
- Audit meaningful writes with actor, before/after state, and reason.

### Tenant and security

- Enforce tenant scope in application queries and PostgreSQL policies.
- Avoid privileged runtime access for normal application behavior.
- Ensure administrative or migration roles are distinct from runtime roles.
- Never use a zero-row ORM result as evidence of absent data without checking
  tenant context.

### User interface

- Provide fleet/client/device navigation and search.
- Provide Issues/findings, Patching, Software, Review, source health, client
  mapping, identity, notification, and policy workflows.
- Use human-readable operator language while preserving internal identifiers in
  storage.
- Make filters and population denominators visible.

## Nonfunctional requirements

- Python 3.12 and the documented Django/DRF dependency range.
- Postgres-backed state and migrations.
- HTMX/server-rendered workflows unless a stronger client-side need is
  demonstrated.
- Deterministic, observable queues with recovery and health thresholds.
- Derived-state refreshes must be ordered and safe to repeat.
- Architecture changes require a decision record when they affect identity,
  storage ownership, security, compatibility, or operational policy.

## Acceptance criteria

- Tenant and RLS behavior is verified.
- Canonical, derived, operator, and effective layers remain distinct.
- Migrations and refresh order are reviewed.
- Django, Ruff, focused tests, and template/request checks pass as applicable.
- Root VERSION and CHANGELOG are updated only for an approved stack release.
