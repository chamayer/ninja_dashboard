# PLAN-049 — Index active findings by subject

**Status: active.** Registered 2026-11-03 from the PLAN-012 follow-up review.
Implemented and committed on branch `plan049-active-findings-index`
(`4cb502e0`, worktree `.work/plan049`); not merged or released. Push and
deployment keep their gates.

## Goal

Counting or listing a subject's active Issues reads only active findings. The
main-navigation Computers page (`/devices/`, `devices_page`) no longer spends
seconds on its severe-Issue column.

## Evidence (production, read-only, 2026-11-03)

- PLAN-042/044's "Computers" measurements are the Coverage inventory
  (`/inventory/computers/`, `fleet_coverage`); `/devices/` was not measured and
  PLAN-044's changes do not touch this query.
- `devices_page` counts severe active findings for a 100-row page by joining
  the page to findings. The planner reads all 29,557 active severe findings
  (11,194 for devices) through `idx_findings_status_severity`: about 18,000
  page reads, 2.3 s (2.4 s cold earlier, 0.56 s best).
- Probing by the page's ids uses `idx_findings_subject` but still reads the
  100 Computers' 4,577 findings of all statuses to keep 204 active ones:
  1.7 to 2.1 s. Results are identical to the join (0 differences).
- 565,000 of 618,560 findings are closed and remain in the table (retention is
  PLAN-019 F05).

## Change

1. Partial index `idx_findings_active_subject` on
   `(tenant_id, subject_type, subject_id, severity)` where
   `status IN ('open','acknowledged','investigating')` (the readers'
   `_FINDING_ACTIVE_STATUSES`), in the model and migration 0404 (after
   PLAN-045's 0403). Plain `CREATE INDEX`, not concurrent (startup migration
   lesson, 0.131.0); it blocks writes to `findings` for seconds at deploy.
2. `devices_page` probes findings by the page's ids
   (`subject_id = ANY (ARRAY(SELECT device_id FROM page))`) so the index is used
   per Computer.

## Validation

- Done locally (worktree): migration/model parity, condition equals the
  readers' active statuses, non-concurrent build, page-probe shape (4 tests);
  `makemigrations --check` clean; Ruff clean on new files. Operations
  non-PostgreSQL suite: 604 passed, 8 failed, the same 8 failing at the branch
  base `e9a48512`.
- Not done: building the index on production-size data (lock time) and the
  post-deploy plan check.
- Acceptance after release (read-only): the `/devices/` findings subquery uses
  `idx_findings_active_subject` and completes in tens of milliseconds; result
  parity with the previous query.

## Dependencies

Migration 0404 depends on PLAN-045's 0403 (in the local WIP commit
`2af7fb1b`); rebase if PLAN-045 renumbers. PLAN-055 occupies 0405 and PLAN-044
now owns 0406 for the Home source-attribution helper. Rebase this branch after
PLAN-044 and renumber the index migration to 0407 or later. The old worktree
`.work/plan049` is absent; resume from commit `4cb502e0` on branch
`plan049-active-findings-index`. PLAN-050 (database memory) affects all
cold-read timings.

## Related

PLAN-012 (found it), PLAN-042/PLAN-044 (Coverage-view performance), PLAN-019
F05 (closed-finding retention), PLAN-050.
