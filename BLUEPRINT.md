# PLAN-012 — Computers inventory read model

## Goal

Make the Computers inventory correct and responsive while preserving its
filter, card, and CSV contract. Requirement state has one authority that pages
read instead of re-deriving.

## Scope

One rebuildable effective read model owned by existing source, identity,
coverage, and Hudu authorities. Preserve tenant/RLS, URLs, cards, filters, CSV,
and source-only rows. No cache or duplicate authority.

User-confirmed order (2026-10-21): (1) stored requirement verdicts; (2) Status
filter including Missing over every agent (not four hard-coded names), one
Hudu card (requirement counts now allowed), card order Ninja, SentinelOne,
LogMeIn, R-U-ON, ScreenConnect, Hudu, then others, and a one-line filter bar
with matching Filter/Clear at the far right.

## Status

Active. Step 1 implemented and validated locally; uncommitted, not deployed.

## Decisions

- ADR-0035 (`operations/docs/decisions/0035-...`): the evaluator's coverage
  pass stores a verdict per Computer and requirement in
  `operations.device_requirement_state` (migration 0332) in the transaction
  that writes its findings. Its only writer is
  `write_device_requirement_state`. Runtime roles get SELECT only.
- Online/Offline stays a live read from `device_agent_presence_current`.
- `check_device_requirement_state` runs after each platform evaluation and
  keeps disagreements in `device_requirement_state_drift`. It does not repair.

## Baseline (production, read-only, 2026-10-21 ~17:00 UTC)

5,420 Computers; 4,853 have a current Hudu asset. The page showed 4,208 Hudu
requirements, all Missing, and 3,946 had no finding. Page-only Missing:
Ninja 57, SentinelOne 51, LogMeIn 42, ScreenConnect 4. Open Missing findings
against finding-backed page rows: Ninja 344/245, SentinelOne 515/420, LogMeIn
162/131. The evaluator runs every ~41 min (248 s).

## Validation (step 1, local)

- Migration 0332 on PostgreSQL 16 with production role attributes: 8 passed.
- Evaluator verdicts on PostgreSQL (Hudu current/archived, stale, outside
  coverage, exempt, single Computer): ingest evaluator and requirement-state
  tests, 33 passed.
- Computers page tests: 16 passed. `manage.py check` and
  `makemigrations --check` are clean.
- Full suites: Operations 441 passed/4 failed; ingest 481 passed/4 failed.
  The same 8 fail on clean HEAD 3091a47.
- Ruff is clean on changed files. `views.py` has the same findings as HEAD.
- Not validated: the deployed stack. The page shows no verdicts until the
  first evaluator run after deploy.

## Checkpoint

Step 1 code: migration 0332, `ingest/evaluator.py` (`_write_requirement_state`),
`ingest/requirement_state.py` with `operator_job_queue` wiring, the Computers
page read in `views.py` and `coverage.html`, tests, ADR-0035, and an
architecture note.

## Next action

User review, then a separately approved commit and push (the push deploys and
applies 0332). After deploy, compare the page with the baseline and read the
drift table. Then step 2. After that, move the Dashboard, software-capability,
and `_auto_resolve` copies to the stored verdicts.
