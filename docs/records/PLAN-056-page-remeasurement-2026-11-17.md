# PLAN-056 — Page remeasurement, 2026-11-17

## Scope and authorization

User requested remeasurement of pages after .26 recovery. Use the existing
plan056_nav_pages.py and plan056_http_pilot.py unchanged: one normal configured
admin login/logout, fifteen sequential default-page GETs, 20 seconds each,
stop at first failure, no retries. Normal session/last-login effects are included.
Internal loopback HTML only; no browser, external network, cold-cache claim,
business action, queue manipulation, deployment or test suite.

## Steps and validation

Confirm healthy services and unchanged deployed collector inputs; create fresh
host/container staging, transfer reviewed files, compare normalized SHA-256,
run by .py path under a 360-second wrapper, capture redacted JSON, check exact
request completion markers with existing plan056_matrix_completion.sh, remove
only exact staged files/directories and confirm absence.

Record all attempted routes, elapsed time/status, logout and cleanup outcomes.
Compare to the retained 2026-11-11 numbered baseline without replacing it.
Single samples establish neither sustained performance nor page correctness.

## Results

Completed at 18:29:08–18:29:42 UTC on 0.144.26 / 0891738b. All four services
were healthy at preflight. Runtime release hashes had matched during the
immediately preceding resume verification. Transfer hashes matched before
execution and again before removal. Exact run prefix:
121f7eb464e7d9a2d5f16de2456bcc4a. All fifteen requests returned HTTP 200,
with one matching status-200 server completion marker each. Logout confirmed
(302, session cookie removed). Host/container staging absence confirmed.

Rows retain the original numbered worklist order. Baseline is the single
2026-11-11 sample; these are different uncontrolled workload/cache conditions,
not a controlled benchmark. Seconds measure complete internal HTTP HTML.

| Page | Baseline s | Current s | Headers s | Bytes |
| --- | ---: | ---: | ---: | ---: |
| Software | 13.094 | 1.230 | 1.230 | 47,355 |
| Inventory: Source records | 7.700 | 1.939 | 1.939 | 137,849 |
| Admin: Sources | 6.346 | 1.013 | 1.013 | 81,331 |
| Inventory: Clients | 5.793 | 2.091 | 2.089 | 207,320 |
| Home | 5.688 | 3.411 | 3.411 | 28,080 |
| Inventory: Computers / Coverage | 4.605 | 3.875 | 3.875 | 427,450 |
| Patching | 4.349 | 5.481 | 5.481 | 125,091 |
| Clients | 3.804 | 3.621 | 3.621 | 160,066 |
| Issues | 2.214 | 2.113 | 2.113 | 91,006 |
| Admin: Health | 1.902 | 2.531 | 2.531 | 481,099 |
| Admin: Overview | 1.355 | 1.319 | 1.319 | 30,906 |
| Admin: Data | 1.238 | 1.388 | 1.388 | 32,709 |
| Computers | 1.195 | 1.390 | 1.387 | 130,165 |
| Admin: Jobs | 1.105 | 1.066 | 1.066 | 60,070 |
| Admin: Settings | 0.147 | 0.155 | 0.155 | 27,790 |

Patching is the slowest observed page. Home misses both its ordinary <=1.5 s
target and <2 s hard maximum. Patching and Admin Health have higher samples
than the retained baseline, but causation/regression is not established by
this pass. Software/Sources/Source Records have substantially lower samples.
No content parity, populated-summary assertion, browser/network performance,
cold state, repeat/percentile or sustained freshness claim follows from 200s.

## Checkpoint

Requested measurement complete; PLAN-056 remains active and page acceptance
remains open. Existing uncommitted documentation and untracked recovery scripts
are preserved. No runtime edits, tests, commit or push. Registry validation and
git diff --check passed. Next review these results and select the next scoped
diagnosis, prioritizing Home's explicit target miss and Patching's observed cost.

## Full pass after Patching .27

User requested the full list again. At 18:57:15–18:57:43 UTC, release
5185e142 / 0.144.27, all four services healthy. Same unchanged navigation
collector, normal configured-admin login/logout, one GET/page, 20-second
deadline and no retries. All 15 requests returned 200 with exact completion
markers under prefix 66290ba042cb07b551162f91010d760b. Transfer hashes matched;
logout and exact host/container staging cleanup confirmed.

| Page | Prior full pass s | Current s | Headers s | Bytes |
| --- | ---: | ---: | ---: | ---: |
| Software | 1.230 | 0.260 | 0.260 | 33,423 |
| Inventory: Source records | 1.939 | 2.145 | 2.145 | 137,850 |
| Admin: Sources | 1.013 | 1.109 | 1.109 | 81,190 |
| Inventory: Clients | 2.091 | 2.141 | 2.141 | 207,320 |
| Home | 3.411 | 1.378 | 1.378 | 27,986 |
| Inventory: Computers / Coverage | 3.875 | 4.214 | 4.214 | 427,637 |
| Patching | 5.481 | 1.423 | 1.422 | 125,155 |
| Clients | 3.621 | 3.764 | 3.764 | 160,078 |
| Issues | 2.113 | 2.172 | 2.172 | 91,006 |
| Admin: Health | 2.531 | 2.423 | 2.423 | 482,382 |
| Admin: Overview | 1.319 | 1.670 | 1.670 | 30,906 |
| Admin: Data | 1.388 | 1.114 | 1.114 | 32,716 |
| Computers | 1.390 | 1.906 | 1.905 | 130,259 |
| Admin: Jobs | 1.066 | 1.068 | 1.068 | 59,960 |
| Admin: Settings | 0.155 | 0.180 | 0.180 | 27,790 |

Software's shorter response prompted one protected runtime-reader state check:
pending/input_changed, has_data=false. Its fast HTML response is not a populated
Software performance result. No recovery or job manipulation was performed.
All earlier cache/network/content-parity limits still apply. Full pass complete;
user next requested a two-minute Coverage bottleneck diagnosis.
