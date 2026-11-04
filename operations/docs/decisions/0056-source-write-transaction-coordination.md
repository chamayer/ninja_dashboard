# 0056 — Coordinate source writes with findings and ownership work

Status: Accepted for local implementation; deployment pending
Date: 2026-11-04

## Context

PLAN-045 added ownership invalidation and reassessment enqueueing to source
writes. Actual PostgreSQL reports show source writes deadlocking with ownership
readers and software reassessment enqueueing. These transactions hold locks on
multiple Computers and queue entries until commit. Sorting one statement cannot
establish a consistent order across all statements and triggers.

Most conflicting producers already enter through the exclusive tenant findings
guard introduced in 0363. Source snapshots and software apply bypassed it.

## Decision and enforcement

Join the existing transaction guard before shared database mutations. The shared
source writer calls `guard_findings_writes` before snapshot creation. Ninja health
and observation backfill use `findings_transaction`. Software apply takes the
guard after API streaming and temporary-table loading, before source-record or
installation writes. Notification delivery joins in shared mode before ownership
and finding row locks, retaining its existing delivery-time ownership fence.

Enforcement is at these application transaction boundaries, tested by unit
boundary checks and concurrent PostgreSQL tests loading the actual 0363, 0370,
and 0401 functions. This does not add a database-wide prohibition on unguarded
SQL; future entry points must follow the same protocol. Existing UI software
decisions already call `guard_findings` before ownership fencing.

## Consequences and validation limits

Snapshot atomicity, trigger admission, rollback, and queue semantics remain
unchanged. No migration or additional queue is introduced. Competing guarded
database transactions in one tenant serialize; ordinary MVCC reads and other
tenants remain independent. API calls in source collection and software streaming
occur outside the exclusive guard. A notification's shared guard lasts through
its existing bounded delivery attempt.

Both recorded lock patterns reproduce without coordination and complete with it
on small synthetic PostgreSQL fixtures using the production functions. Rollback
and tenant separation are tested. Full-schema integration, workload waits, and
live collection recovery remain unverified. Measure workload contention only in
an authorized rehearsal environment; do not infer acceptable delay from local
correctness checks.
