# 0004 — Separate findings from notification responses

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

A detected condition and the decision to notify, suppress, acknowledge, or
route it have different ownership and lifecycle.

## Decision

Findings state observable conditions. Notification rules, suppressions,
cooldowns, and routes determine responses.

## Rationale

The same fact can be reviewed, suppressed, routed, or escalated differently
without changing the evaluator.

## Consequences

- Evaluators do not send notifications directly.
- Finding keys and lifecycle must be stable.
- Notification attempts and outcomes require separate audit records.
