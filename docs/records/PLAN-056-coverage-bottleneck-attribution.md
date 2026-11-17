# PLAN-056 — Coverage bottleneck attribution, 2026-11-17

User authorized three minutes to identify the remaining Coverage cost. One
read-only configured-admin direct handler trace against deployed f8416839/.24;
no login/session write, response/customer payload output, test suite or repeat.
Eight-second statement/one-second lock limits, 45-second process bound; normal
connection closure confirmed. The trace emitted only timings and code locations.

## Observed result

HTTP handler returned 200. Under cProfile instrumentation: 8.046 s handler,
3.224 s SQL execute time across 21 calls. This differs from the earlier 4.830 s
complete HTTP observation: profiler overhead, cache/load and excluded middleware
mean they are not a controlled comparison. SQL execute time excludes fetch and
Python/render processing; the remainder is not an unbiased Python cost estimate.

| Query | Execute seconds | Deployed views.py line |
| --- | ---: | ---: |
| Initial Hudu inventory/lifecycle | 0.7308 | 14541 |
| Source-record totals | 0.6627 | 14686 |
| Stored requirements/presence | 0.5887 | 14481 |
| Compact source observations | 0.5341 | 14632 |
| Selected-page source timestamps | 0.3817 | 15688 |
| Computer inventory | 0.1584 | 14568 |
| Source presence | 0.1007 | 14608 |

The first four total 2.5163 s, about 78% of SQL execute time. No single SQL query
dominates the entire page. The new page-scoped Hudu detail was below the trace's
0.05-second emission threshold; it is not the largest remaining cost here.

Application profile: `inventory_platform_cell` called 34,974 times, 0.3653 s
self / 0.6749 s cumulative; `active_since` 40,907 calls, 0.1378 s cumulative;
`aggregate_hudu` 5,729 calls, 0.1410 s cumulative; filter `matches` 5,729 calls,
0.0267 s cumulative. `fleet_coverage` itself 0.4955 s self. These inclusive
profile costs must not be added as independent phases or treated as proof that
cell construction alone dominates the uninstrumented page.

## Conclusion and next scope

Remaining structural cost is the initial full-population read/assembly path:
four broad reads account for most measured SQL, and row/platform assembly still
visits the fleet before rendering the selected page. Another change to page-only
Hudu detail is not justified by this observation. Preserve the corrected detail
boundary. Next design a compact domain-owned selector and count/summary readers
that preserve all filters/populations while avoiding rich fleet input expansion;
reuse maintained results where compatible rather than inventing a blanket cache.
Any implementation/security/freshness and full-request latency acceptance remain
separate. This trace does not measure each query's internal plan or all template
costs and does not establish lock waits, cache-independent costs or an SLO.

Collector: scripts/diagnostics/plan056_coverage_trace.py. Temporary host/container
copy removed after the single execution. Evidence and checkpoint saved locally;
no runtime changes, migration, commit, push or deployment in this diagnosis.

## Current .27 trace — 2026-11-17

User requested a two-minute diagnosis after the 18:57 full pass (Coverage
4.214 s HTTP). One existing reviewed read-only collector, unchanged, against
deployed .27; same 8-second statement/1-second lock/45-second process limits.
HTTP handler 200, profiled 6.204 s, SQL execute 2.238 s across 21 statements.
Profiler/middleware/cache differences prevent direct comparison with HTTP time.

| Work | SQL execute seconds |
| --- | ---: |
| Stored requirements/presence | 0.5324 |
| Compact source observations | 0.4119 |
| Selected-page source timestamps | 0.4094 |
| Initial Hudu inventory/lifecycle | 0.3914 |
| Protected source-record counts | 0.2095 |
| Computer inventory | 0.1349 |
| Source presence | 0.1011 |

No single dominant query: first four account for 1.7451 s (78% of measured SQL).
Full-population processing remains visible: inventory_platform_cell 34,980
calls (0.3729 s self / 0.5532 s cumulative), aggregate_hudu 5,730 calls
(0.1669 s cumulative), matches 5,730 calls. These profile costs include
instrumentation and cannot explain the entire uninstrumented HTTP duration.
The next optimization target is repeated fleet preparation plus the four reads
above, preserving domain-owned filters/counts and selected-page detail fences.
No evidence justifies dropping page data or changing access/freshness semantics.
Connection closure and exact host/container staging cleanup confirmed. No edits
to runtime, tests, jobs or deployment; deeper query-plan attribution remains open.
