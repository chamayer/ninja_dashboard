# PLAN-017 — Consolidated data architecture review

**Status:** Active. PLAN-018 is absorbed with provenance retained. No design or remediation is adopted. Phase 1 accepted (Point 39; assessment `983872ba…f94f` at `054dcfb`, amended `d2d7a465…4cdf`); evidence in [assessment](docs/records/PLAN-017-phase-1-assessment.md), [gate ledger](docs/records/PLAN-017-phase-1-gate.md), [review](docs/plans/review-plan-017-018.md).

**Phases 2–4** (user-approved, executed by Claude): [Phase 2](docs/records/PLAN-017-phase-2-results.md) reproduced F01/F02/F03/F08, U04 and F07 locally (accepted, Codex round 21); [Phase 3](docs/records/PLAN-017-phase-3-results.md) production incidence: U04 common, F02 plausible in outages, F03 rare, F01 not observed, F08 decided on mechanism; [Phase 4](docs/records/PLAN-017-phase-4-verification.md): U04 generation fence and F08 separate sites scope proven locally, candidates compared. No source, schema or production changes. M6 showed F02 not observed. [Phase 5 draft](docs/records/PLAN-017-phase-5-triage.md) is Point 42. **Next:** Codex consensus on Point 42, then user Q1–Q2.

# PLAN-012 — Computers inventory read model

## Goal

Make the Computers inventory page fast without weakening its full-fleet
contract. Preserve canonical computer data, tenant isolation, coverage
verdicts, source and Hudu state, filters, summary cards, CSV, and
current-versus-withdrawn semantics. Reusable fleet facts move into an owned,
rebuildable read model refreshed after ingest.

## Scope

One rebuildable effective read model owned by the existing source, identity,
coverage, and Hudu authorities, with a refresh function integrated into
`refresh_derived()`. No cache or duplicate authority. Requirement-rule
changes are out of scope; they belong to PLAN-014 (`ingest/BLUEPRINT.md`).

## Status

Active. The read model itself has not started.

Done under this plan (pushed to both remotes):
- `cc5d936`: the evaluator stores requirement verdicts (ADR-0035, migration
  0332). This prerequisite gives the read model one requirement authority.
- `453c41c` and `ccae6da`: Computers page fixes the user requested (card
  order, one Hudu card, Status filter over every catalogued agent, one-line
  filter bar, compact cards, clearer Hudu column, OS "Unknown"). These are
  page fixes, not read-model progress.

Not done:
- no inventory read model or materialized view;
- no refresh function and no `refresh_derived()` integration;
- the route still assembles fleet state from several runtime queries;
- no performance re-measurement, parity validation, release documentation,
  or plan completion.

## Evidence

Deployed 0.128.15 measured Computers at 4.740 s browser first response: 3.154 s
of database wait across 15 fleet reads, plus 1.209 s of template rendering.
That was before `cc5d936`, which replaced the page's requirement derivation
with one indexed read. Re-measure before designing.

Production after the first verdict pass (2026-10-21 17:48 UTC): 19,012
verdicts. Hudu Missing went from 4,208 on the page to 260. The drift check
shows 582 open findings with no matching verdict, which the resolve step's
separate rule copy explains (PLAN-014).

## Validation

Recorded with each commit: migration 0332 and evaluator Postgres tests,
Computers page tests (20), Edge screenshots, and the full suites. Each run
had only the 8 failures that also fail on HEAD 3091a47.

## Checkpoint

Prerequisites and page fixes are deployed. The read-model design has not
started.

## Next action

Re-measure the deployed Computers page. Trace each remaining runtime query
to its authority. Define the read model, its refresh owner and
`refresh_derived()` hook, its tenant boundary, staleness behavior, and
parity checks before implementation. Then move the Dashboard and
software-capability requirement copies to the stored verdicts.
