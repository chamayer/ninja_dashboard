# PLAN-017 — D4 runtime measurement results (part C)

2026-10-25. Executed by Claude under the user's Point 38 direction and explicit
confirmation of the reviewed commands below. Metrics only: no response bodies,
CSV records, customer identifiers, cookies, credentials or raw errors were
printed or retained. Status: **all 15 HTTP shapes measured** (first run plus a
re-measurement under the revised limits); D4.5 not run.

## Baseline caveat (found after the runs)

During this session commit `fcb488a` (migration 0345: restricted source layouts
in the safe metadata view, plus an added `observation.restricted` column in the
`source_records` reader) reached `origin`, which triggers the production
deployment. Its commit time, 19:04 −04:00, is after the first HTTP run
(18:46–18:48 −04:00 by the access log) and likely before the re-measurement and
the D4.5 probes. Whether and when production redeployed was not verified, so
the measurements may span two application/view versions, and D4.5 follows the
pre-0345 reader shape (it omits `observation.restricted`). The local
`source_records` digest now differs from round 15
(see `PLAN-017-gate-evidence/retry-closing-source-delta.json`). Codex A/B probes
also ran on 2026-10-25; overlap with these C runs was not checked.

## Method and conditions

| Item | Value |
| --- | --- |
| Local HEAD at capture | `70e64f5`; reader digests matched `round-15-checkpoint.json`. Deployed application version not verified. |
| SQL path | `Invoke-DevTool.ps1 am-ch-01 ssh` → `docker exec ninja-operations python manage.py shell`, using the app's own runtime connection settings. |
| SQL wrapper | D4 wrapper per statement: read-only transaction, `search_path = operations, public`, lock 1 s, statement 15 s, idle 10 s, tenant 1, rollback. |
| P0 (every statement) | role `operations_app`, server 160014, read-only on, tenant 1, search path `operations, public`, rolsuper false, rolbypassrls false — pass. |
| HTTP path | Host `python3` (`http.client`) on the Docker host → Gunicorn loopback `127.0.0.1:8091`, bypassing any proxy; Host header from configured allowed hosts; no redirects followed. |
| HTTP identity | App account `admin` (tenant 1, app superuser), one login with the `.env` initial-admin credential, approved by the user. Not the `chamayer` identity the earlier draft assumed; admin may see broader in-app scope. |
| Timing meaning | CLI first-byte and full-transfer times, not browser render/DevTools. Gunicorn time-to-first-byte dominates; render/transfer split unknown. |
| Cache condition | No flush or restart. First run of each shape is whatever the server state was; repetitions are sequential and immediate. |
| Side effects | Login created one session row and updated `admin.last_login`; session left to expire (logout is not an approved shape). EXPLAIN ANALYZE executed its queries. |

## SQL — plain plans (EXPLAIN, no execution)

| Probe | Startup cost | Total cost | Est. rows | Max node est. | Access path | Wall ms |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| D4.1 | 13842.07 | 13842.08 | 1 | 92170 | Seq Scan(devices); Index Only Scan(entity_observation_current) | 191 |
| D4.2 | 2130.28 | 2130.29 | 1 | 5513 | Seq Scan(devices) | 9 |
| D4.3 | 11711.77 | 11711.78 | 1 | 92170 | Index Only Scan(entity_observation_current) | 4 |
| D4.4 | 12021.41 | 12021.91 | 200 | 92170 | Index Only Scan(entity_observation_current) → Aggregate → Sort | 6 |
| D4.4b | 13.52 | 13.53 | 1 | 76 | Seq Scan(clients), Seq Scan(source_instances) hash join; Index Scan(sources) | 58 |
| D4.4c | 6.33 | 6.52 | 76 | 76 | Seq Scan(clients) → Sort | 4 |

Gate applied before execution (approved): every P0 pass, wall < 30 s, total
cost ≤ 500,000 and no node estimate > 5,000,000. All passed.

## SQL — execution

D4.1 aggregate: **current_computers = 5,508; source_records = 37,188** (wall 967 ms).

| Probe | Execution ms | Planning ms | Actual rows | Shared hit | Shared read | Temp blocks | Wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D4.2 | 8.692 | 0.805 | 1 | 2025 | 0 | 0 | 24 |
| D4.3 | 61.910 | 0.390 | 1 | 12999 | 0 | 0 | 71 |
| D4.4 | 93.377 | 0.398 | 10 | 5189 | 285 | 0 | 100 |
| D4.4b | 1.632 | 6.707 | 16 | 31 | 5 | 0 | 16 |
| D4.4c | 0.192 | 0.288 | 79 | 3 | 0 | 0 | 4 |

### D4.5 — first Source-record page (plain plan only)

The user waived the D1.11 dependency (part A had not produced D1 results); a
plain plan as `operations_app` fails on any missing column before execution.
P0 passed and the plan built, so every referenced column exists.

| Probe | Startup cost | Total cost | Est. rows | Max node est. | Wall ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| D4.5 | 1164093.74 | 1200866.99 | 100 | 61642 | 336 |

Node chain: `Limit > Result > Sort > Result >` five nested loops over Index
Scan(source_instances), Index Scan(sources), Bitmap Heap Scan(entity_observation_current)
via Bitmap Index Scan(uq_obs_current_tenant_observation), two Index
Scan(evaluator_config), Index Scan(devices); Materialize over Seq Scan(clients);
Materialize over the group-mapping branch (Seq Scan(source_instances), Index
Scan(entity_source_links), Hash over Seq Scan(client_source_mapping_decisions));
and a branch with `Limit > Sort` over Seq Scan(source_instances), Index
Scan(entity_observation_current) and **Seq Scan(entity_candidates)**.

The plan exceeded the 500,000 cost gate. Startup cost ≈ total cost: the
planner expects to produce and sort the full joined set before returning the
first 100 rows. The user then overrode the gate. `EXPLAIN (ANALYZE, BUFFERS,
TIMING)` as `operations_app` passed P0 and was **cancelled by the 15 s
statement timeout** (wall 15,050 ms; reported as `OperationalError`); rolled
back, not retried. No execution metrics exist.

### Deployment timing (checked after the runs)

`ninja-operations` container started **2026-10-25 23:05:29Z** on an image
created 23:05:19Z, about a minute after `fcb488a` (23:04Z). Pre-deploy: the
D4.1–D4.4c SQL run and the first HTTP run (22:46–22:48Z). Post-deploy: the
`/software/` log check, the R1–R3 re-measurement and all D4.5/D4.5r probes.
The `operations_app` read of the Django migration ledger returned no rows (no
error), so ledger visibility is unknown; D4.5r's plan building with
`observation.restricted` shows migration 0345's view column is installed.

### D4.5r — D4.5 reconciled with the post-0345 reader

D4.5 plus `observation.restricted`, as the current `source_records` reader
selects. User approved `EXPLAIN (ANALYZE, BUFFERS, TIMING FALSE)` with a 28 s
statement timeout (sub-batch within 30 s). P0 passed both times.

| Mode | Startup cost | Total cost | Planning ms | Execution ms | Actual rows | Shared hit | Shared read | Temp | Wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| plan | 1668171.19 | 1704944.44 | — | — | — | — | — | — | 375 |
| analyze | 1668171.19 | 1704944.44 | 203.672 | **24326.455** | 100 | 3810233 | 56260 | 0 | 24791 |

Per-node actual rows/loops (TIMING FALSE, so no per-node times):

| Node | Est. rows | Actual rows | Loops |
| --- | ---: | ---: | ---: |
| Index Scan(source_instances), outer side of the observation join | 1 | 16 | 1 |
| Bitmap Heap Scan(entity_observation_current) via uq_obs_current_tenant_observation | 61642 | 37188 | **16** |
| Index Scan(evaluator_config) ×3, under the view's per-row Result | 1 | 0 | **595008** each |
| Index Scan(devices) | 1 | 1 | 37188 |
| Materialize over Seq Scan(clients) | 76 | 48 | 37188 |
| Materialize over the group-mapping branch | 119 | 397 | 37188 |
| Seq Scan(entity_candidates) (proposed-other check) | 13274 | 3883 | 1 |
| Sort before Limit 100 | 308 | 100 (of 37188 input) | 1 |

Reading of these counts (not a verified diagnosis): the planner estimated 1
source instance (actual 16), put instances on the outer side of a nested loop,
and re-scanned all 37,188 tenant observations once per instance
(16 × 37,188 = 595,008 rows). The view's three per-row `evaluator_config`
lookups added by 0345 then ran 595,008 times each. The proposed-other check ran
once, not per row.

The first D4.5 (`TIMING TRUE`, 15 s) timed out; with TIMING FALSE the same work
took 24.3 s, so the timeout reflects real execution cost, not only timing
overhead.

### Post-deploy Source-record page (re-measurement at user direction)

One more login as `admin`, then a single `GET /inventory/source-records/` with
the same script and the revised 90 s HTML limit:

| Route shape | When | Status | Bytes | TTFB ms | Total ms | `<tbody>` rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `/inventory/source-records/` | pre-deploy, reps 1–3 | 200 | 117688 | 8513 / 7298 / 6637 | 8518 / 7304 / 6639 | 100 |
| `/inventory/source-records/` | **post-deploy** | 200 | 117688 | **29622** | **29627** | 100 |

The unfiltered Source-record page went from 6.6–8.5 s to 29.6 s across the
0345 deploy, consistent with D4.5r's 24.3 s first-page query. Response size is
unchanged. Single post-deploy sample; other Source-record shapes and the
Source-record CSV were not re-measured. Attribution to the 0345 view change
rests on the D4.5r plan counts and timing; it is not otherwise verified.

### After the 0346 fix (re-measurement at user direction)

`ee180e1` (migration 0346, restricted layouts joined once) deployed: container
started 23:33:31Z, image created 23:33:21Z. One login as `admin`, then every
Source-record shape once, followed by D4.5r (TIMING FALSE, 28 s) as before.

| Route shape | Status | Bytes | TTFB ms | Total ms | `<tbody>` rows | CSV records |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `/inventory/source-records/` | 200 | 124963 | 9071 | 9076 | 100 | — |
| `?state=active` | 200 | 125010 | 8316 | 8318 | 100 | — |
| `?relationship=attached_computer` | 200 | 126022 | 7361 | 7363 | 100 | — |
| `?page=2` | 200 | 124983 | 9082 | 9085 | 100 | — |
| `?format=csv` | 200 | 6447959 | 14587 | 14767 | — | 37188 |

D4.5r after 0346: execution 7,994 ms (was 24,326), planning 33 ms, total cost
196,684 (was 1,704,944), 335,277 shared hits (was 3,810,233), 6,059 reads; the
per-row `evaluator_config` lookups are now one materialized scan. All five HTTP
shapes completed (49 s total). The regression is gone: HTML pages are 7.4–9.1 s
against the pre-0345 6.2–8.5 s, and the CSV is 14.8 s against 13.7 s. Those
small differences come from one sample each and were not tested further. HTML
size rose about 7 KB per page and the CSV fell by 142 bytes. Neither change was
inspected.

## HTTP — measured requests

Login: `GET /login/` 200, `POST /login/` 302, session established, no retry.

| # | Route shape | Status | Bytes | TTFB ms | Total ms | `<tbody>` rows | CSV records | Complete |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `/inventory/computers/` rep 1 | 200 | 423966 | 8775 | 8785 | 100 | — | yes |
| 2 | `/inventory/computers/` rep 2 | 200 | 423966 | 6362 | 6375 | 100 | — | yes |
| 3 | `/inventory/computers/` rep 3 | 200 | 423966 | 6340 | 6348 | 100 | — | yes |
| 4 | `/inventory/computers/?platform=Ninja` | 200 | 427303 | 6455 | 6462 | 100 | — | yes |
| 5 | `/inventory/computers/?computer_scope=any_online` | 200 | 416316 | 6542 | 6550 | 100 | — | yes |
| 6 | `/inventory/computers/?computer_scope=missing_required` | 200 | 411197 | 6291 | 6305 | 100 | — | yes |
| 7 | `/inventory/computers/?page=2` | 200 | 425650 | 6649 | 6661 | 100 | — | yes |
| 8 | `/inventory/source-records/` rep 1 | 200 | 117688 | 8513 | 8518 | 100 | — | yes |
| 9 | `/inventory/source-records/` rep 2 | 200 | 117688 | 7298 | 7304 | 100 | — | yes |
| 10 | `/inventory/source-records/` rep 3 | 200 | 117688 | 6637 | 6639 | 100 | — | yes |
| 11 | `/inventory/source-records/?state=active` | 200 | 117735 | 6166 | 6169 | 100 | — | yes |
| 12 | `/inventory/source-records/?relationship=attached_computer` | 200 | 117789 | 6467 | 6469 | 100 | — | yes |
| 13 | `/inventory/source-records/?page=2` | 200 | 117537 | 8206 | 8208 | 100 | — | yes |
| 14 | `/inventory/source-records/?format=csv` | 200 | 6448101 | 13459 | 13680 | — | 37188 | yes |
| 15 | `/inventory/clients/` | 200 | 171552 | 2987 | 2992 | 90 | — | yes |
| 16 | `/patching/` | 200 | 124929 | 2403 | 2406 | 128 | — | yes |
| 17 | `/software/` | — | 0 | — | 15018 | — | — | **no — 15 s client deadline (TimeoutError)** |

First run stopped at request 17 (elapsed 125 s after login) under the original
15-second HTML deadline. `/admin/jobs/` and the Computers CSV were not reached;
the CSV would also have been skipped by the original all-HTML < 5,000 ms gate.

### Completion check and re-measurement (revised limits)

The user then revised the limits (HTML 90 s, CSV 120 s, 20-minute budget, one
re-measurement per breached shape after confirmed completion, no < 5 s HTML gate
on the Computers CSV); see the D4 protocol. Before re-measuring, the
`ninja-operations` Gunicorn access log (this run's user-agent lines only) showed
the first-run `/software/` request **completed with status 200, 46,876 bytes**,
logged about 20 s after `/patching/`, with no worker timeout or request-error
lines. Log times match request completion (e.g. 9 s for Computers rep 1 versus
8.8 s measured). A second login (one more session row) preceded:

| # | Route shape | Status | Bytes | TTFB ms | Total ms | `<tbody>` rows | CSV records | Complete |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | `/software/` | 200 | 46876 | 21536 | 21538 | 0 | — | yes |
| R2 | `/admin/jobs/` | 200 | 60547 | 1718 | 1719 | 36 | — | yes |
| R3 | `/inventory/computers/?format=csv` | 200 | 1479841 | 12848 | 12936 | — | 5508 | yes |

`/software/` reports 0 `<tbody>` rows; its table markup was not inspected, so
this is not evidence of an empty page. The Computers CSV record count equals
D4.1 `current_computers` (5,508).

`<tbody>` rows count `<tr` inside `<tbody>` sections of the received HTML; a
coarse table-size indicator, not a parity check. The Source-record CSV count
uses a streaming CSV parser (quoted newlines handled) and equals D4.1's
`source_records` (37,188). Scope/parity per card and filter: **unknown** (not
evaluated by the CLI method).

## Observations (measurements, not diagnoses)

- The runtime SQL kernels are fast (≤ 94 ms execution), while the Computers and
  Source-record HTML pages take 6.2–8.8 s to first byte. Most request time is
  outside these SQL kernels; which queries, Python or template work account for
  it is not decomposed by D4 and remains unknown.
- First runs were ~1.3–2.4 s slower than repetitions on both unfiltered routes.
- `/software/` is the slowest page measured: about 20–21.5 s to first byte on
  both runs, about a third of Gunicorn's default 60 s worker timeout.
- Both CSV exports complete well within 120 s: Source records 13.7 s (37,188
  records, 6.4 MB) and Computers 12.9 s (5,508 records, 1.5 MB). The Computers
  CSV costs about 2.3 ms per record versus about 0.4 ms for Source records.
- `/admin/jobs/` (1.7 s), `/patching/` (2.4 s) and `/inventory/clients/` (3.0 s)
  are the fastest pages.

## Coverage gaps

post-0345 timing of the other Source-record shapes and CSV; pre-deploy runs of D4.5/D4.5r; per-card and filter scope/parity; per-client filter
parity (removed with D4.S); browser render cost; server-side decomposition of
page time.
