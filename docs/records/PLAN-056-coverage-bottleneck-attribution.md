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
