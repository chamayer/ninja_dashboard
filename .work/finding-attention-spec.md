# Stored finding attention (spec, superseded)

Superseded by `.work/finding-state-design.md` (2026-10-15). Kept for history.

Status: proposal. Nothing built. Measured 2026-10-15 against production (read-only).
Replaces the earlier option B sketch after review with the user: no lag in the list, no change to
anything that acts on the outside world, no second long-lived path.

## Problem

The Issues page works out every finding's attention (needs action / blocked / pending / covered)
on each view. For the 39,384 active findings that costs about 10 s:

| Step | Time |
| --- | --- |
| Roll-up from assessments and participants to one value per finding | 7.2 s |
| Finding rows through the ORM | 2.4 s |
| Participants for the critical-priority overlay | 0.7 s |
| Total (`_condition_operator_states`) | 10.0 s |

Filtered Issues pages take 14–17 s because of it. The roll-up depends only on stored assessments,
so it can be stored when the assessment is written. Assessments are already up to an hour old
when the page shows them, so a roll-up written at the same moment adds no lag.

## Design

### What is stored

`operations.findings` gains `attention` (text: `needs_action`, `blocked`, `pending`, `covered`;
null until first computed) and `attention_at` (timestamptz). One SQL function,
`operations.refresh_finding_attention(finding_ids uuid[])`, holds the roll-up rule and is the only
definition of it. The rule is today's: every expected non-context participant has a current
assessment and every one may execute means needs action; any blocked means blocked; a current
suppressed assessment whose reason is `covered_by:*` AND a still-open parent finding on the same
computer means covered; anything else pending.

### What stays live (read when the page loads)

- Pause, acknowledge, resolve: columns on the finding (`snoozed_until`, `status`).
- "Critical takes priority": a small set (about 0.7 s), computed from stored attention instead of
  from a recomputed roll-up.
- Freshness: a stored value older than the active policy's freshness window reads as pending.

### What refreshes the stored value (enforced, not by convention)

1. `ingest.conditions.record_assessment`, the single choke point for all seven evaluators,
   calls the function for the finding after persisting its rows.
2. A trigger on `findings` (`AFTER UPDATE OF status, snoozed_until`, and on insert) refreshes
   the findings that a changed finding covers (same computer, type listed in `covered_by`).
   Findings are closed by about 25 separate `UPDATE` statements across the evaluators and
   resolvers, so a Python hook cannot be complete; the trigger can.
3. When a parent clears, its children immediately read pending ("waiting for reassessment")
   and are queued for reassessment, so the gap is visible and short instead of silent.
4. A ratchet test fails if any code other than the function writes `attention`.

### Consistency check (nothing silently corrected)

A scheduled job recomputes the roll-up for every active finding, repairs any disagreement, and
records an operator-visible finding (`attention_drift`, registered in the finding types registry)
with the old value, the new value and the time.

## Fence: what does NOT change in this work

Notifications, the digest, source actions, the software exposure read model, the live condition
reader and the evaluators' own decisions keep reading assessments exactly as they do. Moving any
of them to the stored value is a separate decision with its own comparison and approval.

## Order of work

1. Migration (additive): the two columns, the partial index `(tenant_id, attention)` on active
   statuses, the function, the `findings` trigger, the one-time fill. Revert is dropping them.
2. `record_assessment` calls the function.
3. Read-only comparison on production: stored value vs the current projection for all active
   findings. Differences are explained before any reader changes.
4. The Issues page reads the stored value behind one setting; the old projection stays as the
   fallback until the comparison has run clean for a period agreed with the user.
5. Remove the old projection (`_condition_response_ids`, the Python roll-up, the fleet SQL) once
   the fallback is retired; the transition has a removal date recorded in the plan.

## Consumers touched (Issues page only)

Issues queue, fleet tiles, type counts, CSV export, Covered view and "N covered" counts, the
device page (`views.py` line ~2967) and the single-finding review (line ~6904, recomputed live
so the page a person acts on is always current). Several tests read `views.py` source text and
need rewriting.

## Risks

- A written value that disagrees with the live rule: covered by the comparison and the drift job.
- Trigger cost on bulk status updates: statement-level where possible; measured before push.
- Policy version change makes stored values stale until reassessed: they read pending until then,
  exactly as a missing assessment reads today.
- The migration deploys on push; the push approval must name it.

## Validation plan

Unit tests for the function's rule on fixtures; the ratchet; trigger tests on Postgres in the
disposable container; the production comparison (step 3); timings of the four filtered Issues
URLs before and after (target about 2 s, from 14–17 s).

## Decision needed

Approve as specified, or amend. No code is written until then.
