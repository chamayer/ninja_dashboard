# 0002 — Separate reporting and operator-control surfaces

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

Relational reporting and interactive operator decisions have different UI,
security, and state-management needs.

## Decision

Use Metabase for read-oriented dashboards and Operations for write-side
control-plane workflows.

## Rationale

Metabase provides efficient filtering and exploration, while Django can enforce
tenant scope, permissions, audit, and validated writes.

## Consequences

- Do not duplicate operator decisions in Metabase.
- Do not rebuild reporting views in Operations without a workflow need.
- Shared metrics require documented authorities.
