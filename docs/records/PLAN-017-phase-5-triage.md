# PLAN-017 Phase 5 — Design and triage (draft for consensus)

2026-10-26. Status: **agreed and closed 2026-10-26.** Codex agreed the dispositions as proposals (rounds 23–24); the user answered Q1 and Q2 (below). Nothing
here is adopted. Per the charter, every material finding gets a disposition,
owner and next action; user questions are asked only after both reviewers
agree their exact wording; accepted future work gets its own approved scope or
ADR. Evidence: [Phase 2](PLAN-017-phase-2-results.md),
[Phase 3](PLAN-017-phase-3-results.md),
[Phase 4](PLAN-017-phase-4-verification.md).

## Dispositions

| Finding | Evidence | Disposition | Owner | Next action |
| --- | --- | --- | --- | --- |
| U04 | Reproduced locally (both producers); precondition ~45 times/day in production; generation fence proven locally incl. in-flight producers. Each lost demand means stale results until the next whole-fleet run, not proven permanent loss | **Fix** | Software jobs (PLAN-002/005/007) | Backlog item: generation column + three producer conflict clauses + fenced acknowledgment; needs a reviewed migration. Phase 4 prototype becomes its test |
| F08 | Reproduced locally; not measured in production (user chose to act on the mechanism); option B proven in a local prototype only | **Fix** | PLAN-002/007 | Backlog item: separate sites snapshot scope (option B), completed only when the sites fetch succeeds |
| F01 | Reproduced locally; not observed in 30 days | **Fix the receipt; keep withdrawal off** | PLAN-002/007 | Backlog item: record an empty `_FETCHERS` result as not-complete instead of `ok=True, rows=0`. Authoritative empty withdrawal only with an explicit per-source policy, never by default |
| F02 | Reproduced locally: a cap hit permanently skips older IDs behind the advanced cursor. Not observed in 30 days (the 6.5-day outage was fully caught up) | **Fix: bounded continuation, with detection first** | PLAN-002/007 | Two backlog items. (1) Detection: a cap hit records the run as partial in the run log. (2) Fix: bounded continuation (design below). Until (2) ships, the risk of losing older events when a backlog exceeds the cap is **explicitly accepted**; detection reports a hit but cannot recover it |
| F03 | Reproduced locally. 3 failed activity runs in 30 days bound the exposure; they do not show any failure fell in the cursor-to-enqueue window | **Fix (small)** | PLAN-002/005/007 | Backlog item: enqueue before advancing the cursor (enqueue is idempotent per computer) |
| F07 | Reproduced on a disposable clean rebuild | **Correct the contract** | No active owner: the projector (`ingest/software_catalog.py`) was last owned by PLAN-011 (completed); PLAN-007 is deferred | Root backlog item marked *owner to be assigned*. Change the docstring's "rebuilds it identically" to in-place rerun only, and state as the current design assumption (not a supported-rebuild guarantee) that catalog rows are retained anchors whose UUIDs authored state depends on. Documentation-only |
| F09 (new, 2026-10-26) | Code-confirmed: `write_daily_presence_rows` is source-agnostic, but the shared `write_observations` writes presence only through its optional `after_current_write` hook, which only the Ninja collector (`ingest/core/devices.py`) passes. SentinelOne, ScreenConnect, LogMeIn, R-U-ON and Hudu records keep no daily presence, so after the 90-day purge they keep no earlier trace at all | **Assess, candidate fix** | PLAN-019 (proposed) | First estimate all-source row growth, retention and operational cost (0.11 GB is Ninja's existing table only, not an estimate for every source); then decide whether the shared writer records presence for every source |
| F04 | Code-confirmed | **Unchanged** | PLAN-012 item 4 | Resume with PLAN-012 once its lost blueprint detail is restored |
| F05a/F05b | Code-confirmed; not measured | **Measure first** | R08, PLAN-006 | Backlog item: measure purge duration and lock waits before choosing batching |
| F06 | Code-confirmed; overlaps U04 | **Map alongside U04** | Software jobs | Map each publication stage and its acknowledgment when U04 is designed. Whether a stage needs a generation fence is a hypothesis per stage; apply one only where that stage's coalescing race is confirmed |
| History expiry (Phase 2 check 10) | Returning record loses its first episode after the 90-day purge while daily presence keeps the day | **Choose a retention option (below)** | R08 | Depends on the user question below |
| Tenant policy cast (Phase 2 check 12) | 0066/0101 policies raise on an empty tenant setting; later policies return no rows. Fail-closed | **Accept; note** | Operations | No change needed; record the inconsistency for the next RLS migration touching those tables |
| Collection logs lost on deploy | Phase 3 | **Operational TODO** (already recorded) | Stack operations | Outside PLAN-017 |

## Retention alternatives for the history-expiry limit

Scope: source records (`entity_observation_current` and its
`entity_observation_history` intervals). The finding is that a source record
returning after its closed intervals passed the 90-day purge has retained
interval history starting at its return. Only Ninja records also keep daily
presence (`source_record_seen_daily`), which preserves earlier observed days;
the other sources keep no earlier trace (F09). Daily presence never shows
continuous presence.

What survives the purge for every source today: the current source record
(latest details, last seen, withdrawal), its open interval, link history (which
client or Computer it was attached to), and the Computer itself. What is lost:
closed intervals, i.e. earlier versions of the record's details and the exact
bounds of past episodes.

Inputs (Phase 1 D2, 2026-10-25, planner row estimates, so approximate; Phase 3
showed one estimate can be badly off): `entity_observation_current` about
92,170 rows; `entity_observation_history` about 572,736 rows in 0.90 GB
including indexes (about 1.6 KB per interval). D5.1's 5,000-row sample: 5 %
open, 63 % closed over 30 days, almost none over 90 days. Intervals churn
quickly and the 90-day purge has only just started to apply (history begins
2026-07-22): about 6 intervals per source record within 90 days, about 6,000
closed intervals a day.

| Option | What it keeps | Estimated steady-state cost | What it does not keep |
| --- | --- | --- | --- |
| Time, 90 days (today) | Every interval of the last 90 days | About 573,000 rows, 0.90 GB | Anything older; a returning record's earlier episodes |
| Time, 365 days | Every interval of the last year | About 4x today: 2.3 M rows, 3.6 GB | Anything older than a year |
| Count, last N per record (N = 3) | The 3 most recent intervals per record, whatever their age | At most 92,170 x 3, about 277,000 rows, at most 0.43 GB | For busy records, most of the last 90 days (about 6 intervals in 90 days on average); weaker than today for recent audit |
| Hybrid: 90 days plus last N (N = 1) | Today's window, plus the most recent closed interval of any record whose intervals are all older | At most 0.90 GB + 92,170 x 1.6 KB, about +0.15 GB (upper bound; only quiet or returned records add rows) | Older episodes beyond the last one |
| Hybrid: 90 days plus first-observed anchor | Today's window, plus `first_observed_at`, its precision and its basis on each current source record for as long as that record is retained | About 92,170 x 10 bytes, about 1 MB, plus a one-time backfill (below) | Any old interval contents; continuous presence |

Anchor and its trail: each current source record carries
`first_observed_at`, `first_observed_precision` (`timestamp` or `day`) and
`first_observed_basis`, which says where the value came from and whether it is
the true first observation, so any reader can explain it. Precision and
certainty are separate: an exact timestamp can still be only a lower bound.

| Basis | Precision | Meaning |
| --- | --- | --- |
| `first_observation` | `timestamp` | Set by the writer when the record is first observed (all records first seen after the change ships). The true first observation |
| `retained_history_lower_bound` | `timestamp` | Backfill: the earliest *retained* history interval. Older intervals may already have been purged, so the true first sighting may be earlier |
| `daily_presence_lower_bound` | `day` | Backfill: an earlier daily-presence day than any retained interval. Day evidence only, never shown as an exact time, and itself a lower bound |
| `current_record_latest_state` | `timestamp` | Backfill fallback when neither exists: the current row's latest observation. Latest-state evidence, not a first sighting |

Readers must show the basis with any backfilled value. With F09, every source
would gain the daily-presence basis going forward.

Recommendation: **90 days plus first-observed anchor.** It resolves the
first-sighting disagreement at negligible cost. If the operator need is the
*contents* of the last episode before a return, 90 days plus last-1 is the
next step (about +0.15 GB upper bound). Longer time windows and pure count
retention are not justified by any measured need. A purge that keeps "last N"
needs a per-record ranking delete instead of today's single cutoff, which adds
purge cost (see F05).

## F02 bounded continuation (design)

When a filter's walk hits the cap, persist one continuation per filter,
`(filter, older_than = oldest ID seen, stop_at = the run's starting cursor)`,
in `ninja_core.ingest_state` before advancing the cursor as today. Each later
run first drains open continuations newest to oldest with `olderThan`, at most
a fixed number of pages per run, through the same capture, store and enqueue
path, and deletes a continuation once it reaches `stop_at`. Storage writes
stay idempotent (`insert_ignore` on the activity ID; `source_events` and the
software queue already coalesce), so overlap between a continuation and the
newest walk is harmless. A continuation outstanding for longer than the
source's activity retention is reported as a gap rather than silently
dropped. Prototype it on the Phase 2 activity harness before implementation.

## Standing-check candidates

- The Phase 2 reproductions become regression tests for each fix (they
  should then fail, i.e. be inverted, when the fix lands).
- Phase 3 M5 overlap count (U04 precondition) and Phase 1 D5.2 empty-success
  receipts (F01), as periodic read-only aggregates.
- After F02/F08 observability lands: count of partial activity runs and of
  sites-partial SentinelOne runs, surfaced on the existing Data/Sources pages.

## Ordered transition

1. Documentation and observability, no schema change: F07 contract, F01
   receipt, F02 cap detection, F03 reorder, F09 presence for every source. Small, independent, safe to
   ship one at a time.
2. U04 generation fence: one migration plus producer/consumer statements;
   the prototype test moves into the suite. F06 stage map at the same time.
3. F08 separate sites scope; F02 bounded continuation (after its prototype).
4. History anchor, if the user chooses it.
5. F05 measurement, then any purge change.

F04 continues under PLAN-012 independently. Each item is a separate backlog
entry with its own approval; this ordering is a recommendation.

## Routing

Proposed (user, 2026-10-26: "why not group them under a plan?"): register
**PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)** with status `ready` and the resume gate "execution of the plan or
any step requires separate explicit user approval". It holds U04, F08, F09
(assess first), F01, F02, F03, F07 and the first-observed anchor in the
ordered transition above, with F06's stage map alongside U04, and so also
gives F07 an owner. Registering it authorizes no implementation and changes no
other plan's status or resume gate: PLAN-002 and PLAN-005 stay `verify`,
PLAN-006 and PLAN-007 stay `deferred`, PLAN-012 keeps F04. PLAN-019
coordinates with PLAN-002/005/007 on the code they cover. F05 measurement
stays a root backlog item under R08 and PLAN-006's gate.

## User answers so far (2026-10-26, pending Codex agreement on wording)

- Q1: the user asked what survives 90 days (answered above) and why Ninja is
  treated specially (answered: a wiring gap, now F09), then said an anchor
  makes sense **as long as the trail can be explained** — met by the
  basis/precision fields.
- Q2: the user asked why the items are not grouped under a plan, leading to
  the PLAN-019 proposal.
- The user asked for Codex to agree the corrected wording before formal
  questions.

## Proposed user questions (revised in Claude round 28 per Codex round 24)

**Q1: first-observed anchor.** "A source record that returns after its closed
history has passed the 90-day purge shows its return as the start of retained
interval history. Today only Ninja records also keep daily presence; other
sources keep no earlier trace (F09 proposes assessing daily presence for every
source). Do you want `first_observed_at` retained on each current source
record for as long as that record is retained, together with where the value
came from and its precision, while detailed interval history stays on the
existing retention policy? **Yes:** records first seen after the change get
their true first observation. Existing records are backfilled from the
earliest retained evidence and labelled as a lower bound: a retained history
interval gives an exact time that is not necessarily the original first
observation, a daily-presence day gives only a day, and records with neither
fall back to their latest observation, labelled as such. It does not restore
prior interval contents or imply continuous presence. **No:** keep the current
behavior."

**Q2: PLAN-019.** "May I register PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up) with status `ready` and the resume
gate that executing the plan or any step needs your separate explicit
approval? It would hold U04, F08, F09 (assess first), F01, F02, F03, F07 and,
only if you choose Yes on Q1, the first-observed anchor, in the agreed order.
Registering it would not authorize implementation or change any other plan's
status or resume gate."

## Closing PLAN-017

Once Codex agrees this triage (or it is amended), the user answers Q1–Q2, and
PLAN-019 is registered (or the items are otherwise recorded), PLAN-017's charter gates are met and the plan
can be marked complete in the registry. Writer/refresh/capacity and
ordinary-user reader parity remain explicitly out of scope, as recorded since
Phase 1.

## Outcome (2026-10-26)

- **Q1: Yes**, and the user added a requirement: "a trail that can show
  significant changes over time". Claude agreed, on condition that PLAN-019
  first measures which fields drive interval churn and that the significant
  field set is admin-managed data. Recorded as operations ADR 0045; it
  replaces the "90 days plus last interval" option.
- **Q2: Yes.** PLAN-019 is registered as `ready` with the gate that executing
  it or any step needs separate user approval.
- PLAN-017 is completed. F05 measurement is a root backlog item.
