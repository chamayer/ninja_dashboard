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

## Scope

- `ingest/evaluator.py` coverage pass: apply decisions 1, 2, and 4, and
  record a verdict for each excluded requirement so nothing disappears
  silently. The verdict name is to be settled; it must stay distinct from
  outside coverage.
- Make the resolve step (`_auto_resolve`) agree with the coverage pass, so the
  drift table stops reporting findings without verdicts. It currently uses a
  separate requirement copy and a fixed 7-day offline window.
- Migration: reword the `os_unknown_coverage` finding type. Extend the
  `device_requirement_state` verdict check if a new verdict is added.
- Computers page: show the new verdicts plainly, with no "Not evaluated" for
  OS, and label no-agent Computers "No agents".
- A decision record superseding 0320's behavior and updating ADR-0035, plus
  tests.

## Measured impact (production, read-only, 2026-10-21)

- 3,106 open missing/stale findings. About 1,968 close under both rules
  (1,897 from the `pending_cleanup` gate, including 498 critical Ninja and
  SentinelOne missing findings kept critical from before the Computers went
  offline). About 37 more close from the OS rule on Computers that are not
  offline. About 1,140 actionable findings remain on live Computers.
- 148 open `os_unknown_coverage` findings become about 91 to 183 reworded
  findings (91 unknown-OS Computers with agents are online).
- 616 Computers are waiting in `pending_cleanup` on the Devices list.

## Status

Ready. Recorded 2026-10-21, not started.

## Validation (planned)

Postgres evaluator tests for each rule and for resolve-step agreement, a
migration test with production role attributes, Computers page tests, and a
read-only production impact check before and after deployment.

## Next action

Settle the excluded-verdict name. Then implement the evaluator and resolve
step, the migration, the page, and the decision record, with tests. Nothing is
committed without approval.
