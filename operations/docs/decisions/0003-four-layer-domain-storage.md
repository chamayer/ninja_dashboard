# 0003 — Separate domain storage into four layers

Status: Accepted
Date: 2026-07-15

## Context

Mixing identity, source-derived state, session data, and operator decisions in
one row allowed refreshes and rule changes to overwrite or invalidate fields.

## Decision

Each operational domain uses:

1. Canonical/configuration data
2. Derived current state
3. Operator decisions or typed overrides
4. An effective read view joining the layers

Storage remains per-domain where constraints differ; shared reads use effective
views.

## Rationale

Ownership and precedence become explicit, derived state remains rebuildable,
and operator decisions survive refresh.

## Consequences

- Consumers read effective views rather than recreating precedence.
- Refresh order is an architectural contract.
- Simple reusable operator values may use governed polymorphic storage; complex
  domain values use typed tables.
