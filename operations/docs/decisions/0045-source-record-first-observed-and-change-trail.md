# 0045 — Source records keep a first-observed anchor and a significant-change trail

Status: Accepted (requirement); design and implementation under PLAN-019
Date: 2026-10-26

## Context

Closed source-record history intervals (`entity_observation_history`) are
purged after 90 days (migration 0074). PLAN-017 found that a source record
which returns after that purge shows its return as the start of its retained
history. Only Ninja records also keep daily presence
(`source_record_seen_daily`), because the shared writer records presence only
through an optional hook that only the Ninja collector passes (PLAN-017 F09);
other sources keep no earlier trace. The current record, its open interval,
link history and the Computer survive; earlier versions of the record's
details do not.

Measured inputs (PLAN-017 Phase 1 D2 estimates, 2026-10-25): about 92,170
current source records and about 572,736 history intervals in 0.90 GB, about
six intervals per record within 90 days.

## Options considered

- Keep today's 90-day time window only.
- Longer time window (365 days, about 3.6 GB).
- Count retention (last N intervals per record).
- 90 days plus the most recent interval of each record.
- 90 days plus a first-observed anchor with an explainable basis.
- A compact long-term trail of significant changes alongside the 90-day window.

## Decision

The user decided (2026-10-26, after PLAN-017's two-reviewer question gate):

1. Each current source record keeps `first_observed_at` for as long as the
   record is retained, with its precision (`timestamp` or `day`) and its basis:
   `first_observation` (set by the writer at first observation — the true
   first sighting), `retained_history_lower_bound`,
   `daily_presence_lower_bound` (day only) or `current_record_latest_state`.
   Backfilled values are lower bounds and are always shown with their basis.
2. Source records also keep a trail that can show **significant changes over
   time** beyond the 90-day window. Which fields are significant is
   admin-managed data, not code.
3. Detailed interval history stays on the existing 90-day policy.

## Rationale

The anchor fixes the first-sighting gap at about 1 MB. The significant-change
trail answers "what changed, and when" for the long term without keeping
every interval: most of the roughly 6,000 intervals closed each day are
expected to be routine, so a field-selected trail should be far smaller than a
longer window. Showing basis and precision keeps every value explainable.

## Consequences

- PLAN-019 must first measure which fields drive interval churn before the
  significant field set and trail storage are designed; the trail's cost is
  not yet known.
- Readers that show a first-observed value must show its basis.
- The trail replaces the "90 days plus last interval" option.
- Implementation needs a reviewed migration and separate approval under
  PLAN-019.

## Supersedes or superseded by

Refines the 90-day closed-history purge of migration 0074; does not change it.
Related: PLAN-017 Phase 5 triage (`docs/records/PLAN-017-phase-5-triage.md`).

## Amendment — no daily presence (2026-10-26)

The user decided that no source keeps daily presence (PLAN-019 F09). Presence
over time is part of the significant-change trail: `active` (withdrawn and
returned) is a significant field from the start, so every source gets first
seen, last seen and each gap without one row per record per day. Measured on
Ninja (PLAN-019 F09 results): 774,069 daily rows collapse to about 8,030
presence stretches when gaps of up to seven days count as one. The anchor's
`daily_presence_lower_bound` basis applies only to a backfill run before
PLAN-022 drops `source_record_seen_daily`; after that, backfill uses the
other bases.
