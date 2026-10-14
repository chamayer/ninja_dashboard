# Finding dependency review (draft for confirmation)

Date: 2026-10-14. Evidence is open findings in production, counted per distinct computer or title.

## Rule

A dependent finding is not shown as separate work while its parent is open on the same scope. It stays
recorded as evidence on the parent, and it resumes by itself when the parent clears and the condition is
still true. Independent facts are never suppressed. This uses the existing condition rules (`gate`,
`suppress_attention`); there is no second model.

## Agreed principle (user, 2026-10-14)

A change in the world becomes exactly one of three things:

1. **An event on the computer's timeline**, if it is expected churn that explains itself (for example a
   re-enrolled agent replacing its old record).
2. **A finding hidden under its parent**, if something else already covers it. It stays a real finding
   (own record, first-seen date and history, still evaluated), is hidden from the default list and shown under
   the parent as "N hidden", and appears again when the parent clears if the condition is still true.
3. **A finding**, only if someone might need to check it and nothing else covers it.

Information is still a finding when there is something to check. Severity says how urgent a checked item is;
it is not a separate "no action" class.

## Two kinds of dependency

- **Suppress** (`suppress_attention`): the condition is true but is not what to work on first. The dependent
  stays a finding, is still evaluated, and carries disposition "suppressed" with the parent as the reason.
  Examples: stalled patching on an offline computer; a withdrawn record under missing-from-source.
- **Gate**: the evidence cannot be trusted, so the condition is neither asserted nor cleared (disposition
  "blocked"). Examples: a failed source collection; an unsettled computer identity.

Rows 5 and 7 are gates; the others are suppress. Not yet verified: how the Issues page displays a suppressed
finding today and whether it can be revealed on demand.

## What exists today

- Three rules in the active policy: `identity` (gate), `collection` (gate), `offline` (suppress_attention).
  29 of 63 types carry them.
- The `offline` rule only fires after `offline_days` = 180, so a computer offline for a week gets none of it.
- Patching types carry `identity` and `offline` but not `collection`: a failing Ninja collection can make
  `patching_stalled` look true for every Ninja computer.
- Rules are generic signals. Nothing says "this finding depends on that finding".

## Proposed parents and dependents

| # | Parent | Dependents | Scope | Evidence | Status |
|---|---|---|---|---|---|
| 1 | device_missing_from_source | device_source_record_withdrawn, device_offline, stale_required_platform, missing_required_platform, patching_stalled, reboot_pending, windows_servicing_unknown | same computer | 148 of 149 computers also carry a withdrawn finding | proposed |
| 2 | device_offline | stale_required_platform, patching_stalled, reboot_pending, patch_failing_repeatedly, device_never_patched | same computer | offline with stale agent: 180 computers (39% of stale); with stalled patching: 224 (20%) | proposed; replaces the 180-day trigger |
| 3 | patching_stalled | reboot_pending | same computer | 124 of 203 computers with reboot pending (61%) | proposed |
| 4 | missing_required_platform | windows_servicing_unknown | same computer | 182 of 228 computers with unknown servicing (80%) | proposed |
| 5 | source_failure | stale_required_platform, missing_required_platform, device_source_record_withdrawn, device_unenrolled, cmdb_asset_stale (already via `collection`); add patching_stalled for the Ninja source | computers of that source | gap: patching types lack `collection` | proposed |
| 6 | jobs_schedule_failure, jobs_timeout, jobs_repeated_failure, jobs_required_disabled | jobs_unmet_dependency (219 open), source_failure for the affected source | same job chain | jobs_unmet_dependency is by definition a symptom of an upstream job | proposed; needs the link key checked |
| 7 | identity conflicts (identity_conflict, duplicate_platform_record, shared_serial, cross_client_serial, unmatched_source_group) | every computer-level condition of the affected computers | same computer | already enforced by the `identity` gate | exists |
| 8 | client_unattached_group | unmatched_source_group for that group | same source group | not measured | candidate |
| 9 | device_unenrolled | missing_required_platform | same computer | not measured | candidate |
| 10 | device_missing_from_source | device_source_record_withdrawn (when no source remains) | same computer | see withdrawn below | proposed |
| 11 | eol_runtime | vulnerable_software | same title | 89 of 131 EOL titles (68%) also vulnerable; one fix (replace) | candidate |
| 12 | review finding (rare_recent, whitelist_suggestion) | known_malicious_hint shown as a signal on it | same title | 48 of 80 hints (60%) are on a non-approved title | candidate |

## Looked at and kept independent

- **missing_required_platform vs device_offline** (341 computers): two true problems, bring it online and install
  the agent.
- **unauthorized_remote_access vs anything:** it is on 4,451 of 5,561 computers, so every overlap with it is
  base rate, not dependency. About 5,200 of its 6,610 open findings are "ScreenConnect client" instances with
  basis "no authorization and not mapped to a required platform". That is an authorization gap to settle once
  per product, not 4,451 problems.
- **windows_servicing_eol, software findings vs offline or patching:** facts about installed state.
- **rare_recent / whitelist_suggestion vs vulnerable_software** (1,329 and 824 titles): a decision and a fact; an
  approval does not silence a vulnerability (D3).
- **patch_approval_backlog:** client-level.

## device_source_record_withdrawn

Finding out *why* a source lost a record is itself the action, so this is not a no-action item. The finding
should work out the likely cause and set its own severity from it (measured 2026-10-14, 2,534 open findings
on 609 computers):

| Likely cause | Findings | Computers | Severity | Treatment |
|---|---|---|---|---|
| Replaced by a newer record in the same source (re-enrolled agent) | 1,703 | 317 | info | explained; sorts last |
| Other sources still report it, no replacement | 266 | 125 | low | the real "find out why": was the agent removed on purpose? |
| No source reports it | 565 | 202 | dependent | evidence under `device_missing_from_source` |

By source, replaced: Ninja 1,395 of 1,773, ScreenConnect 118 of 125, SentinelOne 183 of 483, LogMeIn 7 of 153.
The finding carries the source that withdrew, the record id, when, which sources remain with their last
contact, and the replacement record when there is one. If the withdrawn source is a required platform, the
existing `missing_required_platform` carries the action.

Consequence for presentation: there is no separate "informational" class. Every finding invites a check; what
differs is how likely and how urgent the problem is, which severity already says. Quiet presentation means
info and low sort last and collapse within their category.

## Open questions

1. Which offline threshold does `device_offline` use today, compared with the policy's 180 days? Dependents
   should use the parent's.
2. Row 6: confirm `jobs_unmet_dependency` carries the upstream job key.
3. Rows 8, 9, 11, 12 are candidates; keep, drop or measure first?
