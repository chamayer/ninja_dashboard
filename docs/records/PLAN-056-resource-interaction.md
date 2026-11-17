# PLAN-056 — Resource interaction and recovery implications

## Current status — investigation deferred by user

The user deferred further resource-interaction investigation until larger
demonstrated problems are fixed. Root TODO.md owns resume conditions; proceed
with step 4 remedy comparison without treating this as a prerequisite. The
retained analysis below is evidence, not completion of causal attribution.
The [concrete correlation protocol](PLAN-056-resource-correlation-execution.md)
and three collector files were approved for one attempt. At 23:27:41 UTC,
full statistics/read-only checks passed but no reviewed Job was running, so
the pass stopped before sampling. Cleanup verified; no retry. CPU/I/O ownership,
blockers and naturally observed reader overlap remain unmeasured, deferred work.
The protocol explicitly does not guarantee page causality or exact Job ownership.

## Scope and conclusion

2026-11-10: big-picture step 3, synthesis of retained host, database, HTTP,
Job and targeted Coverage observations. Rechecked the item-5 redacted capture
locally and reviewed connection/observer code. No new production pass, browser,
Job, test, runtime edit, grant or instrumentation change.

**The evidence supports reducing demonstrated excess work before selecting
hardware, memory or concurrency changes.** Coverage has attributed CPU-heavy
execution and an actual-plan amplification mechanism. Other slow pages overlap
database reads, temporary-file work and Jobs, while sampled host resources have
headroom. That combination does not establish one universal contention cause.

This completes the resource-interaction evidence synthesis for comparing
recovery paths. It does **not** complete causal page-versus-Job attribution or
the original database-contention/per-job-cost assessment items. Those gaps
remain explicit conditions on any infrastructure or scheduling proposal.

## What the retained windows establish

| Window | Resource/work evidence | What it supports / does not support |
| --- | --- | --- |
| Initial resource observation, Nov. 9 | 28.95% host CPU busy excluding iowait, 1.27% iowait; 31.18–31.59 GiB available of 62.80 GiB. DB +428,196 blocks read and +87,080,960 temp bytes. Connections 6–9 against configured 100. | Work and temporary files with host headroom; no sampled host RAM/CPU or connection exhaustion. Point samples do not exclude transient/per-core limits. |
| Six-page continuation, Nov. 10, 14:44–14:46 UTC | Resolver running at sampled endpoints; evaluator queued for dependency; source-record assessment running by final snapshot. DB +4,690,376 buffer reads, +403,787,518 temp bytes, but only +31 inserts/+240 updates/+8 deletes. Host 30.13% busy, 1.80% iowait, 30.95–31.31 GiB available. | Slow pages/read/temp work occur even without a large visible committed tuple-write delta in this window. This weakens a universal explanation based solely on concurrent mass writes; it does not rule out waits, uncommitted/buffered writes or statistics lag. |
| Naturally active work, Nov. 10, 19:34:25–19:35:10 UTC | Retained 44.984-second DB interval includes +21,698 updates, of which relationship current +9,994/history +4,997; host 35.04% busy, 1.21% iowait, 30.58–30.78 GiB available. Several Jobs overlap. | Actual write activity exists in normal work. It does not identify the writer, quantify its lock/WAL/vacuum cost or explain a page delay. Truncated first sample prevents reconstructing a full 60-second interval. |
| Main page matrix, Nov. 10, 19:37–19:42 UTC | 24 full HTTP 200 responses, then Coverage timeout; Home 15.908/9.433 s, Software 12.196/15.674 s, Patching 9.647/10.499 s. Host 40.10% busy, 1.39% iowait, 30.40–30.64 GiB available. DB +7,625,620 block reads and +1,070,858,998 temp bytes; concurrent source, matcher, evaluator/resolver/ownership work. | Widespread server-path latency and overlapping work, not host exhaustion or per-query spill/wait attribution. Headers-to-full-body gap at most 0.005 s: this internal-path delay precedes HTML delivery, but includes app/SQL/queue/render work. |
| Targeted Coverage retry, Nov. 10, 20:13–20:15 UTC | Same backend/transaction and Hudu statement retained across eight samples; no sampled blockers/wait events or parallel workers. At one corrective process read: 106.62 CPU seconds over 107.38 seconds backend lifetime, approximately one full core, 827,392 physical read bytes and 2,269,184 write bytes. | Strong CPU-heavy execution evidence for this request; samples do not prove zero intervening waits. Counts include early backend setup, not just Hudu. Actual small original plans independently establish repeated lifecycle work. No successful full-page time was obtained. |
| Item 5 filters, Nov. 10, 21:54:44–21:55:38 UTC | All eight responses complete; Software high-risk 18.080/12.589 s. DB +1,546,994 buffer reads, +312,595,577 temp bytes; resolver present at paired endpoints. | Independent confirmation that filters do not remove all slow work. Global per-interval counters cannot be assigned to the page or resolver. No cache state, role parity or external-network measurement. |

No database reset epoch was certified for these differences: observed reset
timestamps were null. Preserve this limitation rather than claiming exact
per-job rates or a transaction ledger. Nonnegative differences and aligned
windows are evidence of observed activity, not proof of ownership.

## Local reanalysis of the item-5 capture

Recomputed directly from the complete redacted capture; it corroborates the
execution record. These are **whole-database differences during each pair**,
not statements' resource consumption:

| Pair | Buffer reads | Temp files | Temp bytes | Inserts / updates / deletes |
| --- | ---: | ---: | ---: | ---: |
| Computers / Windows | 90,586 | 1 | 5,128,192 | 0 / 8 / 0 |
| Source Records / RMM | 293,770 | 4 | 29,196,288 | 6,734 / 394 / 6,672 |
| Patching / server | 350,535 | 14 | 21,422,597 | 0 / 8 / 0 |
| Software / high risk | 812,093 | 12 | 256,848,500 | 0 / 64 / 0 |

Resolver was the running Job key at the endpoints of each pair; platform
evaluation also appeared in the pass's queued/running snapshot population.
Do not label the Software temp-byte delta as a Software spill or the Source
Records tuple delta as writes by its read-only page. Both could include other
work, observer bookkeeping and delayed statistics publication.

Four retained host CPU samples span the observer interval around this pass:
41.47% busy excluding iowait, 0.76% iowait, available memory
31,777,448–31,969,068 KiB. This interval differs from the precise HTTP/SQL
endpoints and is not a page-level resource share. Current capacity is not
inferred from these historical windows.

## Separate the competing explanations

1. **Excess computation/read amplification: demonstrated for Coverage.**
   Approximately one core can be consumed by one backend while the host still
   has idle cores. More total host CPU is not evidence that this query shape
   will become fast. Other pages have reader deadlines and static broad-query
   leads, but their individual CPU/node costs remain unmeasured.
2. **Database memory, temporary files and physical I/O: unresolved attribution.**
   Historical settings were shared_buffers 128 MiB, work_mem 4 MiB and
   effective_cache_size 4 GiB on a 62.8-GiB shared host. They are inputs to
   review, not a sizing recommendation. PostgreSQL buffer reads may be served
   by the OS cache; counters do not establish physical disk saturation.
   Temporary-file work occurred, but the affected statements and cost are not
   identified. Cross-layer I/O interpretation follows the
   [PostgreSQL 16 monitoring documentation](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-STATS-VIEWS).
3. **Lock/transaction contention: not established platform-wide.**
   Runtime-role observation hides other-session fields, so null waits/empty
   blocker results under that role are inconclusive. A separately authorized
   inspection identity provided full visibility for Coverage state/retry only.
   Those no-blocker samples cannot be generalized to Software, evaluator or
   refresh transactions. Job dependency/capacity waits describe admission,
   not SQL blocking. The relevant visibility rules are documented in
   [PostgreSQL statistics access](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-STATS-VIEWS).
4. **Background write/refresh cost: mechanically plausible, unmeasured impact.**
   Step 2 identifies broad writes, scope expansion and repeated publication
   opportunities. Global writes and known Job durations establish real work,
   not how much latency it adds to a given reader. Statement/family phase
   correlation is required before blaming any particular Job or changing
   correctness guards, periodic freshness or concurrency.
5. **Application concurrency and browser/network: separate gaps.**
   Gunicorn worker/thread configuration does not prove occupancy or queue wait.
   Code uses generic `operations` and `ingest` connection labels; reviewed Job
   child/dispatcher code does not establish a per-run database backend mapping.
   HTTP markers in access logs are not SQL tags. Browser/normal-network effects
   remain unmeasured, but cannot explain away the existing internal slow path.

Historical occupied swap plus observed paging warrants observation, but does
not by itself prove current memory pressure or thrashing. Low host iowait also
does not exclude individual query I/O waits. Root filesystem free space is not
proof of available database-volume capacity or latency.

## What new observation would actually resolve

Another runtime-role global-counter window would repeat the known attribution
gap. If the recovery comparison needs stronger causal evidence, prepare one
concrete correlation pass with the following minimum properties:

- Start from a naturally active reviewed Job/phase; if absent, stop rather than
  force a producer, poll indefinitely or record another idle baseline.
- Use an explicitly authorized existing statistics-capable identity for system
  metadata. No role grants, application-role elevation or business-data reads.
  Past Coverage-specific inspection permission is not blanket authorization
  for a new monitoring scope. PostgreSQL provides monitoring-specific roles;
  see [predefined roles](https://www.postgresql.org/docs/16/predefined-roles.html).
- Bound the proposed passive window to 60 seconds, 13 samples five seconds
  apart, at most 50 active/idle-transaction sessions per sample and one observer
  connection. Use 3/1/5-second statement/lock/idle limits and stop on failure.
  Collect transaction/query ages, wait categories/blocker edges, parallel leader
  relationships and reviewed statement-family aliases; emit no raw SQL, values,
  payloads or connection strings. Keep stable backend/Job aliases within the
  window and preserve truncation/visibility flags.
- Join only proven identifiers or reviewed existing phase/backend metadata.
  A statement family and overlapping timestamps are not exact Job ownership.
  If those identifiers do not exist, state the gap; propose narrowly scoped
  tagging separately rather than claiming attribution or adding instrumentation
  under a read-only task.
- Align host/container CPU, memory/paging and disk-device counters with that
  window. Device/mount mapping and interval deltas are needed before making a
  storage-latency claim; point Docker CPU percentages alone are insufficient.
- Do not add a fresh HTTP request unless it can answer a named comparison and
  server completion can be established. Never replay deferred Coverage, stop
  Jobs, flush caches, change schedules or cancel a backend for this observation.

This is a conditional design for a future observation, not an execution-ready
artifact or pending approval request. Exact queries, redaction, source/visibility
gates, temporary paths, hashes and cleanup must be reviewed before execution.

`pg_stat_statements` was absent and I/O timing disabled in retained metadata.
Do not assume they supply historical per-query counters or enable them as a
casual fallback. Enabling statement tracking can require preload/configuration
and restart depending on installed state; see the
[extension documentation](https://www.postgresql.org/docs/16/pgstatstatements.html).
Sampling alone also misses short statements and intervening waits. Even a
successful passive pass may support family-level overlap without establishing
a causal speedup or per-run write ledger.

## Direction and checkpoint

Proceed to **big-picture step 4: compare recovery paths** with these evidence
boundaries. Query/work reduction is supported as a candidate direction;
capacity-only or concurrency-only recovery is not established. Keep separate:

- A bounded Coverage query correction with measured mechanism/result parity.
- Safe equality/scope reductions in writers, with freshness obligations retained.
- Broader shared-reader/publication changes needing explicit contracts and
  the phase measurements that would determine their value.
- Conditional capacity or scheduling changes requiring attributed waits/I/O/
  pressure rather than headline buffer/temp counts or occupied swap.

Do not describe this as proving that background work causes the slow pages,
eliminating all contention, or completing original assessment items 9–12.
Unknown impact stays a risk/validation requirement in the recovery proposal;
it need not force another broad pre-fix measurement campaign.

Evidence: [assessment windows and Coverage retry](PLAN-056-platform-performance-assessment.md),
[item-5 scope/results](PLAN-056-filter-variants-execution.md),
[shared work](PLAN-056-shared-work-map.md),
[background amplification](PLAN-056-background-amplification.md).
Reanalysis input is the existing complete redacted item-5 capture outside Git.
Source review: `ingest/db.py:init`, `jobs_child.py:main`,
`operator_job_queue.py`, Operations `middleware.py` and production settings;
existing database/host/Coverage collectors. Validation: local capture arithmetic,
source review, registry, whitespace, link and blueprint-size checks. No runtime
tests or new live performance claims.
