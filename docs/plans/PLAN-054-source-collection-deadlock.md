# PLAN-054 — Source collection deadlock repair

## Goal and scope

Release the source/software write coordination repair as 0.144.2 on current
origin/master, preserving the 0.144.1 fixes. Local early notes called this
PLAN-052; the remote registry already uses that ID for Ninja VM analysis.

## Decision and affected files

Reuse the existing tenant findings guard before source/ownership/queue mutations.
Source collection, Ninja health, observation backfill, software apply, and
notification fencing join it. API fetching and software temporary-table loading
stay outside the exclusive guard. No migration or retry mechanism is added.
See [ADR-0056](../../operations/docs/decisions/0056-source-write-transaction-coordination.md).
Tests cover transaction boundaries and the actual lock/queue functions from
0363, 0370 and 0401 using tiny synthetic PostgreSQL tables.

## Checkpoint and evidence

All 49 focused tests pass on this release worktree, including five concurrent
PostgreSQL cases. Both lock cycles deadlock without coordination and commit with
it; rollback and tenant separation also pass. Release preserves the newer
incomplete SentinelOne snapshot handling and source-record presence trail.
Ruff checks, compilation, registry validation and diff checks pass. No commit or push yet.
Production reports: ownership tuple conflicts at 13:39:51, 13:41:05 and
15:33:05 UTC; queue index conflict versus software enqueue at 15:36:53 UTC
(2026-11-04). Read-only logs were inspected; no collection was triggered.

## Validation and next action

Production showmigrations confirms 0401–0404 applied; the ingest ledger matches
all release SQL migrations through 118. No pending or new migrations.
Database workload delays, full-schema integration, and live recovery remain
unverified. Guarded writes in a tenant serialize; ordinary reads and other
tenants remain independent. Do not measure workload performance locally.
Next finish release checks, then obtain separate commit and push approvals.
Root AGENTS.md forbids a separate redeploy despite contradictory operations.md;
follow AGENTS.md and let the approved origin push trigger Portainer.
