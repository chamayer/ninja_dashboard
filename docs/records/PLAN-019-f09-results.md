# PLAN-019 F09 — All-source daily presence estimate

2026-10-26, approved by the user. Read-only production aggregates only; no
writes, no row identifiers. Transport and safeguards are PLAN-017 Phase 3's
(`am-ch-01` helper, `psql` as `operations_migrate`, P0 preflight passed on
every query, read-only, rolled back, 5 s statement timeout). Queries:
[`PLAN-019-f09/queries.sql`](PLAN-019-f09/queries.sql); runner and evidence
JSON in the same folder. Plans were captured first (`plan1`); the first F1/F2/F4
batch failed at the SSH transport (helper exit 255, no result) and was
repeated once as `select1-attempt2`. Database wall time 4.1 s.

## Measurements

| Item | Value |
| --- | --- |
| `source_record_seen_daily` | 774,069 rows (2026-06-02 → 2026-10-26; 335,647 backfilled from legacy), 107 MB with indexes, about **138 bytes per row**. No purge or retention applies to it |
| Ninja presence written per day (last 14 days) | about 5,740 rows: `agent.rmm` 4,660–4,760, `vm.guest` 850–920, `vm.host` 100, network 2, monitor 1. No Ninja org presence |
| Current source records | 37,350 in total (the Phase 1 planner estimate of 92,170 was high) |

Active current records, which is what daily presence would record per day
(seen in the last day matches active for every non-Ninja source):

| Source | Records | Orgs | Rows/day if presence were written | Per year |
| --- | --- | --- | --- | --- |
| SentinelOne `agent.edr` | 4,392 | 81 | 4,473 | 0.23 GB |
| LogMeIn `agent.remote_access` | 3,091 | 105 | 3,196 | 0.16 GB |
| ScreenConnect `agent.remote_access` | 1,098 | 1 | 1,099 | 0.06 GB |
| R-U-ON `agent.monitoring` | 658 | 70 | 728 | 0.04 GB |
| Hudu `cmdb.asset` | 10,589 | 79 | 10,668 | 0.54 GB |
| **All five** | | | **20,164** | **≈ 1.0 GB (7.4 M rows)** |

For comparison, Ninja's presence grows about 0.29 GB a year. All sources
together would be about 25,900 rows and 3.6 MB a day, 1.3 GB a year,
unbounded. The agent sources without Hudu are about 9,500 rows a day,
0.48 GB a year. Write cost is one `INSERT … ON CONFLICT DO NOTHING` per
collection, and repeat runs on the same day insert nothing.

## Observations (not acted on)

- **Ninja presence covers about half of Ninja's active records** for every
  entity type (e.g. `agent.rmm` 9,322 active and about 4,700 presence rows a
  day; `vm.host` 200 and 100). This suggests a second Ninja record set
  (binding or namespace) that writes no presence. Not investigated; check
  before relying on Ninja presence as complete.
- **No Ninja presence on 2026-10-24.** A day with no successful Ninja
  collection, or one that wrote no presence; not investigated.
- `entity_observation_current` is 2.8 GB of table data (including TOAST) for
  37,350 rows, about 76 KB a row. Relevant to F05 and PLAN-012, not to F09.

## Decision needed

Whether the shared writer records daily presence for every source, and with
what retention (presence has none today). Options: all five sources
(about 1.0 GB a year added); agent sources only, leaving Hudu documentation
records out (about 0.48 GB a year); or none. The Ninja coverage gap above
should be understood first, because the shared-writer change would use the
same mechanism.
