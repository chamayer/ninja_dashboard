# PLAN-017 Phase 3 — Incidence results

Status: **approved scope executed.** The user approved the
[query draft](PLAN-017-phase-3-query-draft.md) parts A (M0–M5) and B (L1),
then Revision 1 (M1r–M3r, L1r) and Revision 2 (M2r at 15 s), on 2026-10-26.
F08 is decided on mechanism and was not measured: M1 and M1r both planned a
full history scan and stopped, and the user chose not to rewrite it again.
Evidence JSON and the runner are in [`PLAN-017-phase-3/`](PLAN-017-phase-3/).

## Execution

Through the shared helper (`am-ch-01` SSH profile), `psql` in
`ninja-postgres` as `operations_migrate`, one fresh connection per statement
with P0 passing every time (role `operations_migrate`, read-only on,
PostgreSQL 16.14, tenant context 1, search path `pg_catalog`, BYPASSRLS).
Every transaction rolled back. Database wall time so far: 2.8 s (M0), 0.6 s
(plans), 5.7 s (M4/M5), 1.0 s (Revision 1 plans), 5.2 s (M2r, cancelled), 0.3 s
(M3r), 3.7 s (M2r at 15 s) — 24.5 s in total, within the 60-second budget. One Revision 1 plan
attempt failed at the SSH transport (helper exit 255, no result) and was
repeated once under a new evidence label. Only counts, bounds and
index definitions were returned.

## Results so far

| Query | Result |
| --- | --- |
| M0 | All seven relations present with every expected column. Retained data starts: org history 2026-07-22, source events 2026-08-05, job runs 2026-09-23, consumed software targets 2026-10-13. `operations.run_log` has **no** `activities` rows. `source_events` has no `received_at` index. |
| M1–M3 plans | M1 planned a parallel sequential scan of `entity_observation_history` (cost ≈ 97,000) — stopped. M2/M3 read the wrong run table — stopped before planning. |
| M4/M5 plans | Sequential scans only of small tables (≈ 52,000 targets, ≈ 8,800 job runs); accepted. |
| M4 (U04 direct) | 0 of 14,477 consumed `cve_match` targets and 0 of 37,559 `inventory` targets have `queued_at` inside their consuming run (since 2026-10-13). **Lower bound only:** the matcher sets `queued_at = now()`, which is its transaction start, so a matcher transaction that began before the findings run and committed during it is not detected. |
| M5 (U04 overlap) | 537 findings runs in 30 days. Producers finished inside a findings run: `software-queue-drain` 1,373 of 4,977 runs, `intel-matcher` 34 of 98, `software-enqueue-orgs` 9 of 23. The U04 window opens about 45 times a day. |
| L1 | `operations-ingest`: 0 cap lines, 0 sites-failure lines — but the container started 2026-10-26 13:28 UTC and does not run the scheduled collection jobs (they run in `ninja-jobs-worker`), so these zeros are not evidence. |
| M1r plan | Restricting to SentinelOne/ScreenConnect instances still planned a sequential scan of `entity_observation_history` (the instance filter became a hash join) — stopped. F08 incidence remains unmeasured. |
| M2r | Plan used an index-only scan of `source_events` (estimated 366,601 entries); the SELECT hit the 5-second statement timeout (SQLSTATE 57014), was cancelled and rolled back. F02 volume remains unmeasured. |
| M2r at 15 s (F02) | Completed in 3.7 s. Over 30 days of Ninja events by activity time: 403 type-days; the busiest event type peaked at **51,651 events in one day**; 14 type-days over 10,000 and 1 over 50,000. Counts include only captured events, so events dropped by a cap would be missing from them. |
| M3r (F02/F03) | Since 2026-09-26: 417 activity runs, 3 failed, 0 unfinished. Median gap between successful runs 1 hour; **longest gap 6 days 12.5 hours**. |
| L1r | `ninja-jobs-worker`: 0 cap lines, 0 sites-failure lines; it was also recreated 2026-10-26 13:28 UTC, so no logs predate today's deploy. Log evidence for the 30-day window does not exist. |

## Interpretation so far

U04's precondition is common in production: inventory and matcher jobs
routinely finish while a findings run is in progress. Whether a given overlap
loses demand depends on whether the same title changed after the run read it;
M4 cannot see that for inventory and only partly for the matcher. Recovery is
the next whole-fleet findings run. This supports treating U04 as a real
staleness source, with impact still unmeasured.

F03: 3 failed activity runs in 30 days bound how often the
cursor-before-enqueue interruption could have occurred; a failure inside the
narrow window between `_set_last_id` and the enqueue is required, so actual
losses are at most a few and likely none. Recovery is the daily fleet check.

F02: the cap (100,000 events per event-type filter per run) is reachable
only when a backlog builds. Hourly runs never approach it, but M3r shows one
6.5-day outage between successful runs, and M2r shows single event types
reaching 10,000–51,651 events a day on 14 days. A 6.5-day backlog for such a
type could exceed the cap, in which case the run after the outage kept only
the newest 100,000 and the older events were never collected. The planner's
earlier estimate (≈ 367,000 events in 30 days in total) was badly low and is
withdrawn as evidence. F02 is therefore **plausible in production during
outages**, not proven: the aggregate does not show which day the peak fell on
or whether the outage window has a gap for that type, and the logs from that
period are gone. A per-day count for the busiest type across the outage
window would settle it; it was not part of the approved scope.

F08: unmeasured. A further rewrite would have to force an index path (for
example `source_instance_id = ANY (ARRAY(...))`) and be re-reviewed.

F01: Phase 1 D5.2 measured none in 30 days.

F08: decided on mechanism (user, 2026-10-26). The fix is small — report a
failed sites fetch as a partial snapshot — so further measurement costs more
than the decision is worth.

## Summary for Phase 4/5

| Finding | Production evidence | Phase 3 reading |
| --- | --- | --- |
| F01 | 0 empty successful collections in 30 days (Phase 1 D5.2) | Mechanism only; not observed |
| F02 | One 6.5-day activity outage; event types up to 51,651/day | Plausible during outages; unproven |
| F03 | 3 failed activity runs in 30 days | Rare at most |
| F08 | Not measured | Decided on mechanism |
| U04 | Producer finished inside a findings run ~45 times/day | Common precondition; staleness until the daily full run |

Collection logs do not survive a deploy, so log-based incidence is not
possible today; this is recorded as an operational TODO, outside PLAN-017.
