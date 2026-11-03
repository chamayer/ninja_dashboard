# PLAN-050 — Database memory and host capacity

**Status: ready.** Registered 2026-11-03 from the PLAN-049 diagnosis. Defined,
not started. Any configuration change, restart or host change is a production
operation with its own approval; nothing here is automatic.

## Goal

The Ninja Dashboard database has a cache sized to its working set, on a host
with enough memory headroom that it does not swap, so page and job timings
reflect query design rather than disk reads.

## Evidence (production, read-only, 2026-11-03)

- PostgreSQL settings: `shared_buffers` 128 MB (configuration file),
  `effective_cache_size` 4 GB (default), `work_mem` 4 MB (default),
  `maintenance_work_mem` 64 MB (default), `random_page_cost` 4 (default),
  `max_connections` 100. Database size 31 GB.
- Overall buffer hit rate 95.8%, but large page queries read thousands of
  blocks from outside the cache on every run (for example 18,000 for one
  Computers-page subquery, repeated).
- Host `am-ch-01`: 35 GB RAM, about 4.7 GB available; swap 8 GB with 96 kB free
  (fully used). The host is shared: Zabbix production database about 9.0 GB,
  Graylog data node about 5.0 GB and Graylog about 3.7 GB, Zabbix server
  400 MB, ninja-postgres 352 MB, Jobs worker 293 MB, Operations 256 MB, and
  others.
- Prior page timings (PLAN-042, PLAN-044, PLAN-012 Stage 2) were taken under
  these conditions; cold and warm runs differ by up to 30 times.

## Questions to answer before any change

1. Why swap is exhausted and which process holds it; whether the host is
   overcommitted regardless of PostgreSQL.
2. The Ninja Dashboard working set: which tables and indexes the hot pages and
   jobs read (sizes are known: about 2.7 GB observations, 1.3 GB condition
   assessments, 1.3 GB software history, 1.1 GB software installations,
   0.7 GB findings), after PLAN-047 and PLAN-048 shrink some of them.
3. A safe target: `shared_buffers`, `effective_cache_size`, `work_mem` and
   `maintenance_work_mem` sized to the memory the host can give PostgreSQL
   without swapping, and whether that needs more host RAM, a memory limit on
   other workloads, or moving a workload.
4. How the configuration is managed (the compose file mounts a configuration
   file; the change must be in the repository, not ad hoc on the host).

## Steps

| Step | Item | Gate |
| --- | --- | --- |
| 1 | Read-only host and database measurements: per-process memory and swap, PostgreSQL buffer usage per relation, cache hit rates per hot table, checkpoint and temp-file statistics. | Read-only production approval |
| 2 | Proposal: target settings and host capacity plan, with the expected effect and the risk to other workloads on the host. Record the decision (ADR if it sets an operational policy). | User decision |
| 3 | Change the configuration in the repository (compose/postgresql configuration); rehearse the restart behavior. | Change approval |
| 4 | Apply in a maintenance window (PostgreSQL restart), then re-measure the same pages and jobs read-only. | Production change approval |

## Risks

- Raising PostgreSQL memory on a host already swapping can slow every service on
  it, including Zabbix and Graylog.
- A PostgreSQL restart interrupts ingest, Jobs and Operations.
- Measurements taken before PLAN-047/PLAN-048 overstate the working set.

## Related

PLAN-049 (found it), PLAN-047 (write volume and bloat), PLAN-048 (record JSON
reads), PLAN-042/PLAN-044 (page timings), PLAN-041 (host CPU).
