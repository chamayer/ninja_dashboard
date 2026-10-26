# PLAN-017 — Consolidated data architecture review

**Status:** Active; Phase 1 accepted by independent review. PLAN-018 is absorbed with provenance retained. No design or remediation is adopted.

The accepted assessment is anchored to HEAD `054dcfb`, SHA-256 `983872ba…f94f`. Corrected assessment SHA-256: `d2d7a465…4cdf`. Claude’s N1–N6 wording corrections are applied or verified; findings, owners, and the 7–16 engineer-day later-phase range are unchanged. Evidence: [assessment](docs/records/PLAN-017-phase-1-assessment.md), [gate ledger](docs/records/PLAN-017-phase-1-gate.md), [Point 39/40 review](docs/plans/review-plan-017-018.md), and `docs/records/PLAN-017-gate-evidence/`.

**Phase 2:** Claude's user-approved 12 checks completed at HEAD `03f71b6` in disposable testcontainers PostgreSQL (34 passed; tested paths clean). Reproduced F01/F02/F03/F08, both U04 producers, and F07 clean rebuild. Holds: first client/Computer publication, catalog repair, expiry, move/undo/reappearance, tenant scope. Results/limits: [record](docs/records/PLAN-017-phase-2-results.md); review: Point 41. No production access or changes. Codex round 21 accepted the reproduced mechanisms as local evidence; its qualifications and the added matcher control are applied (Claude round 23). **Next:** Phase 3 needs separate approval; its unexecuted [query draft](docs/records/PLAN-017-phase-3-query-draft.md) awaits the user.

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
