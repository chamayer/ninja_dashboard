# PLAN-039 — Source-record case combining

Status: Deferred; defined 2026-10-29. Not started; registry owns lifecycle.

## Goal

Let operators combine related investigations when PLAN-004’s related-case view
and duplicate references no longer serve the actual workflow.

## Scope boundary

Require an audited same-problem/same-action decision; preserve qualified findings,
membership, history, permissions, closure and counts. Do not infer transitive
identity or merge Computers. Decide survivor/old-link/split behavior only from
concrete examples; coordinate notification continuity if PLAN-040 is active.

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
