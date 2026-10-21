# PLAN-014 — Requirement applicability

## Goal

An agent requirement applies only where it can be decided positively. Each
missing or stale finding then describes a live, known Computer that an
operator can act on.

## Decisions (user, 2026-10-21)

1. Positive on OS: a requirement applies only when the Computer's OS group is
   known and on the requirement's or agent's supported list. Unknown OS means
   not required, even when the agent has been seen. Hudu still applies
   because its list includes "Unknown".
2. Lifecycle gate: requirements do not apply to Computers whose lifecycle is
   `pending_cleanup` (offline past the configurable retire-review threshold,
   30 days by default). Lifecycle, not agent findings, is the decommission
   gatekeeper.
3. No "alive elsewhere" exception: only 1 offline Computer had non-agent
   evidence of being alive.
4. One finding per unknown-OS Computer that is not `pending_cleanup`:
   "Operating system unknown: agent requirements not applied". This
   replaces the meaning of `os_unknown_coverage`.
5. Existing findings that stop applying are covered, not closed (ADR-0031
   cover): add `device_offline` to `missing_required_platform.covered_by`
   (stale already has it), and add `os_unknown_coverage` to both types'
   `covered_by`, through an audited migration. Cover uncovers live when the
   Computer returns or its OS becomes known. No new policy version and no
   bypass of the clearing check.
6. Computers page labels: "N/A — OS unknown" (OS unknown), "N/A — Offline"
   (`pending_cleanup`), and "No agents" (no agent records). The page does not
   mirror cover. In the 7-30 day window it keeps showing Missing/Stale next
   to the agent's Offline record status (146 Computers, about 130 findings
   on 2026-10-21).

## Scope

Evaluator coverage pass and resolve step, migration 0333 (verdicts, cover
rules, finding wording, drift check), Computers page labels, ADR-0036, and
tests.

Rationale and the clearing constraint are in ADR-0036.

## Measured impact (production, read-only, 2026-10-21)

- 3,106 open missing/stale findings. About 1,968 stop applying (1,897 from
  the `pending_cleanup` gate, including 498 critical missing findings blocked
  today, plus about 37 from the OS rule). These become covered. About 1,140
  remain on live Computers.
- 148 open `os_unknown_coverage` findings become about 91 to 183 reworded
  findings (91 unknown-OS Computers with agents are online).
- 616 Computers are waiting in `pending_cleanup` on the Devices list.

## Status

Active. Implemented and validated locally on 2026-10-21, committed with
ADR-0036 and migration 0333. Deployment and the post-deploy check are pending.

## Validation

- Migration 0333 on PostgreSQL with production role attributes: 3 passed. This
  caught a constraint-order bug before deployment.
- Evaluator Postgres tests: 34 passed (unknown OS applies nothing and raises
  one finding, a seen agent does not apply, `pending_cleanup` records only).
- Computers page tests: 20 passed. Full suites: Operations 445 passed,
  ingest 481 passed, with the same 8 failures as clean HEAD.
- `manage.py check` and `makemigrations --check` clean; no new lint findings.

## Next action

User review, then separately approved commit and push. The push applies 0333
and refreshes about 3,100 finding states. After deployment, trigger
`platform-evaluate` and compare covered counts and drift with the measured
impact.
