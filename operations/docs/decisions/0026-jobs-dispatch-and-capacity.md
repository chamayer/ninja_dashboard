# 0026 — Jobs dispatch and capacity

Status: Accepted
Date: 2026-10-06

## Decision

Jobs keeps four separate concerns:

| Concern | Authority |
|---|---|
| Operator organization | Operations and their visible executable steps |
| Lifecycle | The durable Job run and its structured wait evidence |
| Platform capacity | Execution-resource pool claims |
| Data safety | Domain resource claims |

This record supersedes ADR-0024 only where that record makes a lane or a
deployment-wide execution count the ordinary admission policy. Its durable
ledger, immutable definition snapshots, revision dependencies, fencing,
isolated children, recovery, and RLS requirements remain authoritative.

## Lifecycle

The physical run ledger retains its compatible `queued` status. Its presented
lifecycle is derived from durable evidence:

- `queued` with a dependency/workflow wait is **Waiting for data**.
- `queued` with a conflicting domain claim is **Waiting for protected work**.
- `queued` with unavailable execution capacity is **Waiting for capacity**.
- `queued` without a wait reason is **Ready**.

Only Ready work is counted as queued in operator surfaces. A database
coordinator permits at most two Ready runs across the deployment. Waiting work
is retained, explainable, and never silently discarded.

## Capacity and safety

Definitions declare `capacity_keys` separately from `resource_keys`. Initial
execution pools are `capacity:external-io` (2), `capacity:processing` (1), and
`capacity:control` (1). A definition can claim more than one pool. A separate
deployment-wide emergency child ceiling of four is a safety fuse, not ordinary
scheduling policy.

Domain resource claims remain capacity one and cannot be changed through the
capacity control surface. They serialize actual overlapping publishers: a
definition claims a domain only when it publishes that domain's state. Reading
source or intelligence data does not require a domain claim; a handler instead
uses its selected input state and leaves inputs that change during evaluation
for the next targeted reconciliation. Broad locks may be narrowed only after
handler review proves that this exact-state/follow-on rule preserves
correctness.

## Dispatch and workers

Postgres owns Ready promotion, claim fencing, pool capacity, domain capacity,
and the emergency ceiling. Claims acquire all required identities in stable
order and leave no partial ownership when any check fails.

Workers are stateless supervisors. They own only their local isolated child
processes and may scale without leader election. `SKIP LOCKED`, claim tokens,
and generation fencing prevent two supervisors from executing the same run.

## Consequences

The old lane/global claim path remains only for immutable queued definitions
created before this decision; it drains under its historical policy. New
definitions use execution pools. Jobs surfaces use plain lifecycle language;
pool and claim details remain administrator diagnostics. Capacity adjustments
are audited pool-policy changes, not correctness-lock edits.
