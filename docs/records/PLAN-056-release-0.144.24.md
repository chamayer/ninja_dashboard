# PLAN-056 — Release 0.144.24 deployment and measurement

2026-11-17. User approved commit/push including migration 0418, then measurement
without tests. Commit f8416839 pushed to origin, then a-m-rose. Portainer picked
up that revision automatically; no manual redeploy. Operations, ingest and Jobs
worker healthy; ingest reports 0.144.24 and Operations reports 0418 applied.

## One-pass navigation observations

15:28:16–15:28:48 UTC. One configured-admin internal complete HTML GET per page,
all HTTP 200; normal logout confirmed. No repeat requests or test suite. The
preceding .23 pass was 14:56:44–14:57:19 UTC. Cache state/worker identity/load
were uncontrolled, so these are observations, not a causal speedup benchmark,
ordinary-user certification or proven cold-path performance.

| Page | .23 seconds | .24 seconds |
| --- | ---: | ---: |
| Home | 3.647 | 1.532 |
| Issues | 2.499 | 2.388 |
| Clients | 3.801 | 4.272 |
| Computers | 2.191 | 1.714 |
| Patching | 3.805 | 3.987 |
| Software | 0.259 | 0.300 |
| Inventory Clients | 2.287 | 2.267 |
| Inventory Computers / Coverage | 5.148 | 4.830 |
| Inventory Source Records | 2.042 | 2.412 |
| Admin Overview | 1.790 | 1.510 |
| Admin Data | 1.157 | 1.184 |
| Sources | 1.640 | 1.443 |
| Jobs | 1.711 | 1.169 |
| Admin Health | 2.000 | 2.175 |
| Settings | 0.189 | 0.238 |

Coverage remains slow: the page-scoped Hudu detail boundary does not settle the
initial fleet reads/filter/summary work. Home meets the <2-second hard maximum
in this observation but misses the <=1.5-second ordinary target by 0.032 s.
No navigation item has an accepted disposition from these samples alone.

Software protected read immediately afterward: state=stale, reason=input_failed,
has_data=false. Its fast HTML response is an unavailable summary, not successful
populated acceptance. Failed input attribution/recovery was not attempted here.

Used reviewed plan056_http_pilot.py / plan056_nav_pages.py and the bounded
read-only plan056_overview_read_state.py. No response content, credentials,
customer records or exception text was emitted. Temporary scripts are removed
after the pass. No tests or repeat timing runs. Results recorded locally after
the already-pushed release; no second deployment for measurement documentation.

## Next action

Prioritize the failed Software input and Coverage's remaining initial fleet
work under scoped authorization. Keep the protected reader and badge changes;
neither removing badges nor bounding Hudu detail alone has met Coverage's budget.
