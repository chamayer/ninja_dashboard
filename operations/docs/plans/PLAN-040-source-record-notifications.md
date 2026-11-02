# PLAN-040 — Source-record notifications

Status: Deferred; defined 2026-10-29. Not started; registry owns lifecycle.

## Goal

Enable useful alerts for native record/case findings while preserving existing
notifications and preventing unauthorized context disclosure.

## Scope boundary

Start with a concrete rule and MSP destination. Decide old/new evidence, delayed
evaluation, material changes, suppression, cooldown, no-route/backlog and legacy
retirement behavior. Do not assume first-opened time is evidence age. Reuse the
existing dispatcher and add conversion machinery only when actually needed.

## Activation note and resume gate

This is a brief placeholder, not a completed design. **Improve and expand it when
activating:** inspect the current implementation, gather concrete use cases,
confirm user decisions, then define the smallest scope, affected files, acceptance
criteria, validation and rollout before implementation approval. Update the registry
and active handoff at that time.

Depends on PLAN-004's stable record/case IDs and assessments. Coordinate PLAN-003
and the other PLAN-039/040 follow-up if scopes overlap; neither follow-up blocks
the smaller PLAN-004 release. Resume only with explicit user approval. No runtime,
migration, production operation, commit or deployment is authorized by this plan.
