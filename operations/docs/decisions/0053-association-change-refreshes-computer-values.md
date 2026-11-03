# 0053 — An association change refreshes the Computer values it moves

Status: Accepted
Date: 2026-11-02

## Context

Attribute claims are keyed by source record but carried a copy of the record's
entity, refreshed only by the periodic claim projector during a collection
refresh. Since migration 0374, `set_source_association` changes the association
at once. A Computer created by the resolver therefore kept placeholder values
(`os_group = 'Unknown'`, `device_role = 'unknown'`) until the next collection,
and platform evaluation opened `os_unknown_coverage` for it: 460 of 905
Computers created in 30 days had one on their first day (production,
2026-11-02). Operator merges, splits and moves had the same lag. Record-level
facts (ADR-0050 row 1) were unaffected; the lag hit the Computer's reconciled
values (OS, OS group, role, type) that machine-level rules read.

## Options considered

- Re-run claim and effective projection inside the resolver before the cache
  projector: resolver-only, ordering-dependent, misses operator actions.
- Hold machine-level rules until values are recalculated: delays coverage and
  needs a reliable "recalculated since last change" marker.
- Compute Computer values at read time: one more copy of the selection rules and
  a recomputation on every page read.
- Make the association procedure refresh what it changed (selected).

## Decision

The user approved (2026-11-02): `set_source_association`, the one association
writer, refreshes in the same transaction the claims of the record and its
companions, the effective values of its old and new entity, and the cache
columns of their Computers. It reuses the existing projectors with a scope
filter (one copy of each rule) and the database cache rule
(`device_cache_targets` / `project_device_cache`). If the periodic projector
holds its lock, the refresh defers with a database warning instead of waiting;
the running collection chain completes the work. No operator-visible record is
kept for deferrals, because they resolve within that chain.

## Rationale

The association writer is the only place every attachment change passes
through, so every writer (resolver, merge, split, move) gets fresh values
without ordering rules. The work is proportional to association changes, not
fleet size.

## Consequences

- Enforced by the call in `set_source_association` (migration 0400); the
  one-argument projector functions remain as wrappers.
- About 350 ms per association change (rehearsal on a production schema clone).
- Placeholder values on a new Computer last only until its first association
  commits.
- A source instance without authority rules still yields `no_evidence`; that is
  PLAN-046, not a lag.

## Supersedes or superseded by

Refines ADR-0012 (shared projector authority) and 0374 (association authority).
Related: ADR-0050, PLAN-012 item 4.
