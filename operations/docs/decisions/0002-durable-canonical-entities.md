# 0002 — Keep canonical entities durable

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

Deleting a device because one source stopped reporting it loses history and
confuses source absence with real-world deletion.

## Decision

Canonical entities are never automatically deleted because of observation
staleness. Lifecycle and source absence become explicit state or findings.

## Rationale

This preserves auditability and lets operators distinguish offline, missing,
retired, and source-failure conditions.

## Consequences

- Derived current-state rows may expire or rebuild.
- Canonical deletion is an explicit operator action.
- Coverage denominators use documented lifecycle/scope policy.
