# Refresh derived state after collection

## Status

Accepted

## Context

Source collectors write auditable observations and run records, while
interactive Operations pages intentionally read compact current and derived
structures. Scheduled and on-demand collection paths did not consistently
refresh those structures afterward. Raw source data could therefore be current
while the Dashboard's freshness state remained old.

## Decision

Refreshing dependent current and derived state is part of source collection
completion. The rule applies equally to scheduled, startup, and on-demand
collection paths.

Shared Operations source collection calls `operations.refresh_derived()` at a
common post-collection boundary. Domain collectors that own a narrower current
structure, such as Software's `software_installations_current`, may continue to
refresh it inside their collector rather than redundantly invoking the shared
coordinator.

A refresh exception is surfaced to the caller. An on-demand queue entry must
not be marked successful when collection persisted but its dependent derived
state did not refresh. Source-run evidence remains independently auditable so
operators can distinguish collection failure from refresh failure.

## Consequences

- Dashboards and workflows see newly collected data as soon as a run completes.
- Scheduled and operator-triggered runs have the same freshness semantics.
- A collection can persist raw data and still report a failed completion when
  its derived refresh fails; retrying the refresh is safe and does not require
  recollecting the source.
- Concurrent on-demand source runs may serialize on materialized-view refresh
  locks. Correct completion takes precedence over avoiding a redundant refresh.
