# PLAN-017 Phase 4 — Targeted verification and candidate comparison

2026-10-26. Status: **complete.** Local prototypes passed and M6 (user-approved
2026-10-26) settled F02. Inputs:
[Phase 2 results](PLAN-017-phase-2-results.md),
[Phase 3 results](PLAN-017-phase-3-results.md). Nothing here changes source,
schema or production; candidates are proposals for Phase 5 triage and the
owning plans.

## Local prototypes

Code: [`PLAN-017-phase-4/checks/`](PLAN-017-phase-4/checks/), on the Phase 2
disposable testcontainers fixtures. Each prototype applies a candidate design
to copies of current SQL inside a throwaway database. Run:
`RUN_POSTGRES_INTEGRATION_TESTS=1 .venv/Scripts/python.exe -m pytest -p no:cacheprovider docs/records/PLAN-017-phase-4/checks -q`
— 10 passed; `ruff check` clean.

| Prototype | Result |
| --- | --- |
| U04 generation fence (`test_p4_u04_generation_fence.py`, 8 passed) | Candidate: a `generation` column; producers' conflict clause becomes `DO UPDATE SET generation = target.generation + 1` (current statements rewritten mechanically); the consumer captures `(id, generation)` and acknowledges only unchanged generations. For both inventory and matcher producers it keeps demand in the Phase 2 losing interleaving, and in two cases Phase 2 did not cover: a producer transaction uncommitted at capture that commits before the acknowledgment, and one still uncommitted at the acknowledgment (the acknowledgment waits on the row lock, then leaves the row pending). Uncontended capture → acknowledgment still consumes, and a later change creates a new pending row. A timestamp fence was rejected on analysis: the matcher's `now()` is its transaction start, so a transaction begun before capture would still look older. |
| F08 options (`test_p4_f08_partial_sites_options.py`, 2 passed) | A — mark the whole run partial when the sites fetch fails: the empty site survives, but an agent that really left is not withdrawn that run. B — give sites their own snapshot scope, completed only when the sites fetch succeeded: the empty site survives **and** the departed agent is withdrawn. B dominates A. |

## Candidate comparison

| Finding | Production reading (Phase 3) | Candidates | Recommendation | Owner |
| --- | --- | --- | --- | --- |
| U04 | Precondition ~45 times/day; recovery by the daily full run | (1) generation fence; (2) claim-at-capture so producers insert a fresh pending row; (3) accept staleness until the full run | **(1)**: one column plus three conflict clauses and the consume statement, proven locally including in-flight producers; no change to job scheduling | PLAN-002/005/007 (software jobs) |
| F08 | Not measured; decided on mechanism | A whole-run partial; B separate sites scope | **B**, proven locally; A is an acceptable stop-gap only if B's scope change is deferred | PLAN-002/007 |
| F02 | Not observed: M6 shows the 6.5-day outage was fully caught up | (1) make a cap hit durable — record the run as partial and log it in the run log; (2) persist a per-filter continuation (filter, `olderThan`, stop ID) and drain it before the newest walk; (3) raise the cap | **(1)**; (2) only if a cap hit is ever recorded. A one-day burst of 51,651 events of one type shows an outage of a day or more during a burst could still reach the cap | PLAN-002/007 |
| F03 | 3 failed activity runs in 30 days | (1) enqueue before advancing the cursor; (2) one transaction for capture, cursor and enqueue; (3) derive demand from retained `source_events` | **(1)**: `enqueue_activity` is idempotent per computer (`ON CONFLICT … WHERE status = 'pending' DO NOTHING`), so a replay after a crash costs at most one extra rescan | PLAN-002/005/007 |
| F01 | Not observed in 30 days | (1) route empty results through the run primitives with an explicit "empty is authoritative" policy per source; (2) keep the early return but record the receipt as not-complete instead of `ok=True` | **(2) now** (removes the false-healthy receipt at no withdrawal risk); (1) only with a per-source policy, because an API glitch returning `[]` would otherwise withdraw a whole source | PLAN-002/007 |
| F07 | Reproduced locally on clean rebuild | (1) correct the projector contract: in-place rerun only, catalog rows are retained anchors; (2) build a reconstruction that preserves product/version UUIDs | **(1)**; (2) only if a recovery plan ever needs it | R06/R08 under PLAN-017; catalog owner |
| F04 | Not re-measured | — | Unchanged: PLAN-012 completion-gate item 4 | PLAN-012 |
| F05a/F05b | Not measured in Phase 3 | Bounded/batched purge; total job bound | Measure purge duration and lock waits first; not decided here | R08; PLAN-006 |
| F06 | Not measured in Phase 3 | Stage-specific acknowledgment map | Overlaps U04: the same fence pattern applies to each publication stage; map stages in Phase 5 | Software/Jobs owners |

## M6 — settle F02 (approved and executed)

Question: during the longest activity outage in the last 30 days, did a
high-volume event type lose its oldest events to the cap? If the cap was hit,
the run after the outage kept only the newest 100,000 events of that type, so
the earliest outage days show a hole relative to the later ones.

Role, wrapper and stop rules as in the
[Phase 3 draft](PLAN-017-phase-3-query-draft.md), with the 15-second statement
timeout approved for M2r. Plain plan first; stop on a sequential scan of
`source_events`. Output: the outage bounds and, for the three busiest event
types in that window (as ranks, not names), events per day.

```sql
-- M6 (F02): events per day for the three busiest Ninja event types across
-- the longest outage between successful activity runs, 30 days.
WITH ok_runs AS (
 SELECT started_at FROM ninja_core.run_log
  WHERE domain = 'activities' AND status = 'ok'
    AND started_at >= now() - interval '30 days' AND started_at < now()
), gaps AS (
 SELECT lag(started_at) OVER (ORDER BY started_at) AS gap_from, started_at AS gap_to
   FROM ok_runs
), outage AS MATERIALIZED (
 SELECT gap_from, gap_to FROM gaps WHERE gap_from IS NOT NULL
  ORDER BY gap_to - gap_from DESC LIMIT 1
), ninja AS MATERIALIZED (
 SELECT si.id FROM operations.source_instances si
   JOIN operations.sources s ON s.id = si.source_id
  WHERE si.tenant_id = 1 AND lower(s.name) = 'ninja'
), per_day AS MATERIALIZED (
 SELECT e.event_type, date_trunc('day', e.event_at) AS day, count(*) AS events
   FROM operations.source_events e, outage o
  WHERE e.tenant_id = 1 AND e.source_instance_id IN (SELECT id FROM ninja)
    AND e.event_at >= o.gap_from - interval '2 days'
    AND e.event_at < o.gap_to + interval '2 days'
  GROUP BY e.event_type, date_trunc('day', e.event_at)
), ranked AS (
 SELECT event_type, dense_rank() OVER (ORDER BY sum(events) DESC) AS type_rank
   FROM per_day GROUP BY event_type
)
SELECT (SELECT gap_from FROM outage) AS outage_from,
       (SELECT gap_to FROM outage) AS outage_to,
       r.type_rank, p.day, p.events
  FROM per_day p JOIN ranked r USING (event_type)
 WHERE r.type_rank <= 3
 ORDER BY r.type_rank, p.day;
```

Reading: a cap hit shows as a type whose daily counts fall to near zero for
the earliest outage days while later outage days are high, with the total for
the outage near or above 100,000. Even counts across the outage mean no cap
hit. Like M2r, counts include only captured events.

### M6 result

Executed 2026-10-26 as `operations_migrate`, read-only and rolled back, P0
passing, 15-second statement timeout; plan first (index-only scan of
`source_events`, run log by index); SELECT 1.27 s, 31 rows. Evidence:
`PLAN-017-phase-3/p4-m6-plan.json`, `p4-m6-select.json`.

The longest outage ran 2026-09-29 03:45 → 2026-10-05 16:15 UTC. For the
busiest event type, outage days have ordinary counts (127–188 on weekdays,
16–51 at the weekend), matching 179 the day before the outage, so the
catch-up run collected the whole gap. The 51,651 peak is activity dated
2026-10-05 itself, a one-day burst; the outage-window total for that type,
including all of 2026-10-05, stays below 100,000. Ranks 2 and 3 show the same
shape. **F02: not observed in the 30-day window.** The mechanism remains.
