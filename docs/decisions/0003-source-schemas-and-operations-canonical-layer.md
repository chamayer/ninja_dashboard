# 0003 — Preserve source schemas and add a canonical Operations layer

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

Forcing heterogeneous providers into one raw schema loses source fidelity, but
operator workflows need source-independent clients, devices, findings, and
decisions.

## Decision

Keep source-branded raw/domain schemas and build source-agnostic canonical and
effective structures in the Operations schema.

## Rationale

This preserves source evidence while allowing connectors to be replaced or
combined without rewriting operator workflows.

## Consequences

- Identity resolution is a platform responsibility.
- Source records remain individually auditable.
- Canonical entities must not be treated as disposable source cache rows.
