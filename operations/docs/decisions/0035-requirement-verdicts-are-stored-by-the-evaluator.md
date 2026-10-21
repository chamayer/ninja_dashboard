# 0035 — Requirement verdicts are stored by the evaluator and read, not re-derived

Status: Accepted
Date: 2026-10-21

## Context

The evaluator's coverage pass decides, for every Computer and effective
requirement, whether the requirement is met. It stored only the failures, as
`missing_required_platform` and `stale_required_platform` findings. Anything
that needed the met requirements too (Required, Online, Offline) re-derived the
whole rule: profile or global baseline, client overrides, exemptions, OS
groups, presence. There were five copies: the evaluator's Python, the SQL it
uses to resolve findings, the Computers page, the Dashboard, and software
capabilities.

The copies drifted. Migration 0312 (2026-10-16) made Hudu documentation
(`cmdb.asset`) a requirement. The evaluator saw Hudu assets, but the Computers
page built presence from `agent.%` rows only and fell back to "Missing" when
nothing matched. Measured on production on 2026-10-21: of 4,208 Hudu
requirement rows, the page showed all 4,208 as Missing, and 3,946 of them had no
evaluator finding. 4,853 of the 5,420 Computers had a current Hudu asset. Smaller
page-only Missing counts existed for Ninja (57), SentinelOne (51), LogMeIn (42)
and ScreenConnect (4): Computers the evaluator does not assess.

## Options considered

- Fix the page's copy. Rejected: it remains a copy, and the next requirement
  type would drift again.
- A shared SQL view that derives verdicts. Rejected: the rules that decide them
  live in the evaluator's Python (the agent universe, OS Unknown, the
  stale-gap ladder, collection blockers), so a view would be a sixth copy.
- Store the verdicts where they are decided. Selected.

## Decision

`operations.device_requirement_state` (migration 0332) holds one row per
Computer and effective requirement. Each row records:

- the verdict: `satisfied`, `missing`, `stale`, `exempt`, `not_evaluated` (OS
  Unknown and not established), or `outside_coverage` (no agent records, so
  not in the coverage universe);
- the last qualifying observation;
- the condition key of the finding it produced, if any;
- `evaluated_at`.

Its only writer is `operations.write_device_requirement_state`, called by the
coverage pass in the transaction that writes its findings. A full pass replaces
every Computer's verdicts; a single-Computer pass replaces only that Computer's.
The runtime roles have SELECT only, and only `ninja_ingest` may execute the
writer.

Consumers read verdicts and do not re-derive the rule. The Computers page
reads them first. Online/Offline stays source evidence: the page reads it live
from `device_agent_presence_current` for satisfied requirements. A finding is
still the work item (severity, confidence, lifecycle, notifications); a
verdict is the current answer for met and unmet requirements alike.

After each platform evaluation, `operations.check_device_requirement_state`
compares the verdicts with the open missing/stale findings. It keeps each
disagreement in `device_requirement_state_drift` from first to last sighting
and clears it when it disappears. It does not repair: the evaluator is the
authority, so a disagreement is a defect to explain.

## Rationale

The verdict is computed on every pass and was discarded. Storing it with the
findings it produced, in one transaction, gives one place where the met and
unmet halves live, so they cannot disagree with each other at commit time.
Missing and Stale were already as old as the last evaluator run (about 41
minutes on 2026-10-21), so storing them adds no lag. Online/Offline, which
changes between runs, is not stored.

## Consequences

- A verdict is as old as the last coverage pass. The Computers page shows when
  that was, and says so when no verdicts exist yet (before the first pass after
  deployment).
- Computers outside the coverage universe show "Not evaluated" instead of
  "Missing". The `computer_scope=missing_required` shortcut and the Missing
  counts now match the evaluator's findings.
- The Dashboard and software-capability copies, and the evaluator's own
  resolution SQL in `_auto_resolve`, still re-derive requirements. Moving them
  to the stored verdicts is follow-up work under PLAN-012; the drift table
  measures the cost of waiting.
- The page shows a satisfied Hudu requirement as Offline in the requirement
  status filters, because Hudu reports no online status.
- Migration tests use production role attributes: `operations_migrate` is a
  superuser with BYPASSRLS and owns the table.

## Supersedes or superseded by

Follows the stored-state pattern of ADR-0031. Requirement policy is described
in `docs/architecture.md` (requirement profiles and client overrides).
