# 0036 — Agent requirements apply only to known, live Computers

Status: Accepted
Date: 2026-10-21

## Context

A requirement comes from the client's profile by role. The operating system
only removed agents that cannot run there. Migration 0320 then applied an
OS-limited requirement on a Computer with an unknown OS when the agent had
been seen there, and otherwise reported it as "not evaluated". The coverage
pass also kept raising missing findings on Computers that had been offline
for months.

Measured on production on 2026-10-21: 505 Computers have no operating system
reported. 764 Computers with agents are entirely offline, 616 of them in
`pending_cleanup`. 1,929 of the 3,106 open missing/stale findings were on
entirely offline Computers, including 498 critical missing findings. These
were blocked forever, because the offline signal stops `may_clear`. A resolve
rule meant to close stale findings on offline Computers could never pass its
own clearing check.

## Options considered

- Keep "required unless the OS excludes it" and the presence-established
  exception from 0320. Rejected: it asserts a requirement from evidence other
  than the OS, and the agent's own presence makes it required.
- Close the findings that stop applying. Rejected: closing needs a fresh
  `may_clear` assessment, and closing would churn findings for Computers that
  come back.
- An "alive elsewhere" exception for offline Computers with non-agent
  evidence. Rejected: it applied to one Computer.
- Apply requirements positively, and cover the findings that stop applying.
  Selected.

## Decision

- An OS-limited requirement applies only when the Computer's OS group is known
  and on the requirement's or agent's supported list. An unknown OS applies
  none of them, even where the agent has been seen. A requirement whose list
  includes "Unknown" (Hudu) still applies.
- No agent requirement applies to a Computer in `pending_cleanup` (offline past
  the configurable retire-review threshold). Lifecycle decides those
  Computers.
- Each such requirement is still recorded as a verdict: `os_unknown` or
  `pending_cleanup` (shown as "N/A — OS unknown" and "N/A — Offline"). Each
  unknown-OS Computer that is not in `pending_cleanup` gets one
  `os_unknown_coverage` finding: "Operating system unknown: agent
  requirements not applied".
- Existing missing and stale findings that stop applying are covered
  (ADR-0031), not closed. `missing_required_platform` and
  `stale_required_platform` are covered by `device_offline`,
  `device_missing_from_source` and `os_unknown_coverage` (migration 0333).
  Cover is live, so they uncover when the Computer returns or its OS becomes
  known.
- The evaluator's fixed 7-day offline resolve rule is removed. The drift
  check treats a covered finding next to an `os_unknown` or `pending_cleanup`
  verdict as agreement.

## Rationale

A requirement is asserted only from a fact that decides it. Cover was built
for findings that a parent condition explains, and it keeps one finding's
history without churn. Lifecycle already owns the decision about Computers
that have gone quiet.

## Consequences

- About 1,968 of the 3,106 open findings stop applying and become covered.
  About 1,140 remain on live Computers.
- Covered findings stay open (not "needs action") until the Computer returns,
  its OS becomes known, or it is retired.
- On Computers offline 7 to 30 days, requirements still apply. Their findings
  are covered by `device_offline` while the Computers page still shows
  Missing or Stale next to the agent's Offline record. The page does not
  mirror cover.
- `os_unknown_coverage` findings opened before this change keep their original
  details key; labels read either key.

## Supersedes or superseded by

Supersedes the presence-established and "not evaluated" behavior of
migration 0320. Amends ADR-0035: `not_evaluated` is replaced by `os_unknown`
and `pending_cleanup`.

Amended 2026-10-27 by [ADR-0047](0047-requirement-lifecycle-reconciliation.md):
an explicit valid confirmation that a cleanup Computer is still in use
restores requirement checks while preserving OS applicability and safety
guards. This is an accepted policy amendment; implementation remains pending.
Cleanup status alone does not establish an offline condition.
