# PLAN-017 Phase 5 — Design and triage (draft for consensus)

2026-10-26. Status: **draft by Claude for Codex review (Point 42).** Nothing
here is adopted. Per the charter, every material finding gets a disposition,
owner and next action; user questions are asked only after both reviewers
agree their exact wording; accepted future work gets its own approved scope or
ADR. Evidence: [Phase 2](PLAN-017-phase-2-results.md),
[Phase 3](PLAN-017-phase-3-results.md),
[Phase 4](PLAN-017-phase-4-verification.md).

## Dispositions

| Finding | Evidence | Disposition | Owner | Next action |
| --- | --- | --- | --- | --- |
| U04 | Reproduced locally (both producers); precondition ~45 times/day in production; generation fence proven locally incl. in-flight producers | **Fix** | Software jobs (PLAN-002/005/007) | Backlog item: generation column + three producer conflict clauses + fenced acknowledgment; needs a reviewed migration. Phase 4 prototype becomes its test |
| F08 | Reproduced locally; not measured | **Fix** | PLAN-002/007 | Backlog item: separate sites snapshot scope (option B), completed only when the sites fetch succeeds |
| F01 | Reproduced locally; not observed in 30 days | **Fix the receipt; keep withdrawal off** | PLAN-002/007 | Backlog item: record an empty `_FETCHERS` result as not-complete instead of `ok=True, rows=0`. Authoritative empty withdrawal only with an explicit per-source policy, never by default |
| F02 | Reproduced locally; not observed (6.5-day outage fully caught up) | **Fix observability; defer continuation** | PLAN-002/007 | Backlog item: a cap hit records the run as partial in the run log. Per-filter continuation only if a cap hit is ever recorded |
| F03 | Reproduced locally; at most rare (3 failed runs in 30 days) | **Fix (small)** | PLAN-002/005/007 | Backlog item: enqueue before advancing the cursor (enqueue is idempotent per computer) |
| F07 | Reproduced on a disposable clean rebuild | **Correct the contract** | Catalog owner, R06/R08 | Change the projector's "rebuilds it identically" docstring to in-place rerun only; record that catalog rows are retained anchors. Documentation-only |
| F04 | Code-confirmed | **Unchanged** | PLAN-012 item 4 | Resume with PLAN-012 once its lost blueprint detail is restored |
| F05a/F05b | Code-confirmed; not measured | **Measure first** | R08, PLAN-006 | Backlog item: measure purge duration and lock waits before choosing batching |
| F06 | Code-confirmed; overlaps U04 | **Fold into U04 pattern** | Software jobs | Map each publication stage's acknowledgment when U04 is designed; apply the same fence where a stage coalesces |
| History expiry (Phase 2 check 10) | Returning record loses its first episode after the 90-day purge while daily presence keeps the day | **Choose a retention option (below)** | R08 | Depends on the user question below |
| Tenant policy cast (Phase 2 check 12) | 0066/0101 policies raise on an empty tenant setting; later policies return no rows. Fail-closed | **Accept; note** | Operations | No change needed; record the inconsistency for the next RLS migration touching those tables |
| Collection logs lost on deploy | Phase 3 | **Operational TODO** (already recorded) | Stack operations | Outside PLAN-017 |

## Retention alternatives for the history-expiry limit

Sizes from Phase 1 D2 (2026-10-25): `entity_observation_history` 0.90 GB,
`software_installation_history` 1.39 GB, `source_record_seen_daily` 0.11 GB,
`entity_observation_current` 3.0 GB. Today: closed intervals are purged after
90 days; open versions and current rows are kept.

| Option | Protection | Cost | Limit |
| --- | --- | --- | --- |
| Time (today) | Last 90 days of intervals | Baseline | A record that leaves and returns loses earlier episodes; history and presence then disagree on first sighting |
| Count | Last N intervals per identity, whatever their age | Grows with identities × N; unbounded in time for stable records | Needs a per-identity ranking purge; heavier than today's single cutoff |
| Hybrid — anchor | Time purge as today, plus a durable `first_observed_at` (and optionally episode count) on each current record | One timestamp per current record, negligible against 3.0 GB | Keeps first sighting and continuity facts, not the old interval contents |

Recommendation: **hybrid anchor**. It removes the first-sighting disagreement
at negligible cost and keeps today's purge. Count retention is not justified
by any measured need.

## Standing-check candidates

- The Phase 2 reproductions become regression tests for each fix (they
  should then fail, i.e. be inverted, when the fix lands).
- Phase 3 M5 overlap count (U04 precondition) and Phase 1 D5.2 empty-success
  receipts (F01), as periodic read-only aggregates.
- After F02/F08 observability lands: count of partial activity runs and of
  sites-partial SentinelOne runs, surfaced on the existing Data/Sources pages.

## Ordered transition

1. Documentation and observability, no schema change: F07 contract, F01
   receipt, F02 durable cap record, F03 reorder. Small, independent, safe to
   ship one at a time.
2. U04 generation fence: one migration plus producer/consumer statements;
   the prototype test moves into the suite. F06 stage map at the same time.
3. F08 separate sites scope.
4. History anchor, if the user chooses it.
5. F05 measurement, then any purge change.

F04 continues under PLAN-012 independently. Each item is a separate backlog
entry with its own approval; this ordering is a recommendation.

## Proposed user questions (require Codex agreement before asking)

**Q1 — Retention of returning records' history.** "When a computer or source
record disappears for more than 90 days and later returns, its earlier history
is purged, so the system then shows its first sighting as the return date
(daily presence still records the earlier days). Should we keep the original
first-sighting date permanently? Option A: yes — store a first-seen date on
each record (negligible storage; recommended). Option B: no — keep today's
behavior."

**Q2 — Routing.** "PLAN-017 recommends seven fixes (U04, F08, F01, F02, F03,
F07 and the history anchor if chosen in Q1), each as its own backlog item
under the plan that owns the code, in the order above. Approve adding them as
backlog items? Adding them does not authorize implementation; each still
needs its own approval."

## Closing PLAN-017

Once Codex agrees this triage (or it is amended), the user answers Q1–Q2, and
the backlog items are recorded, PLAN-017's charter gates are met and the plan
can be marked complete in the registry. Writer/refresh/capacity and
ordinary-user reader parity remain explicitly out of scope, as recorded since
Phase 1.
