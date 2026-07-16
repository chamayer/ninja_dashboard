# 0001 — Use one source-agnostic observation pipeline

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

Parallel per-source compliance models duplicate identity, lifecycle, findings,
and notification behavior.

## Decision

All operational connectors emit observations into the shared Operations
pipeline while preserving source-specific raw schemas and evidence.

## Rationale

Platform behavior should not depend on Ninja or any other single provider.

## Consequences

- Connectors collect and describe observations; the platform resolves identity
  and evaluates conditions.
- Source-specific schemas remain for fidelity.
- New connectors must follow the observation contract.
