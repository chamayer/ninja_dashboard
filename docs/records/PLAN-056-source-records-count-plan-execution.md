# PLAN-056 — Source Records default-count plan check

Prepared 2026-11-10 as the next unmeasured reader component after the Sources
record-count plan. The [task 5 frontier](PLAN-056-sources-counts-plan-execution.md)
confirmed that the opaque companion function's actual share is not exposed by
EXPLAIN. Existing function counters are not suitable for request attribution:
the prior resource snapshot did not capture `track_functions`, no baseline
exists for the failed Sources count, and counters aggregate across workloads.
PostgreSQL documents the tracking switch and aggregate counters in its
[`pg_stat_user_functions` reference](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-USER-FUNCTIONS).
No instrumentation change is proposed.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the default, unfiltered Source Records matching-count
SELECT from `source_records`, on am-ch-01 through `Invoke-DevTool.ps1`, inside
Operations using the existing runtime database role. One connection, tenant 1,
read-only transaction, 3-second statement, 1-second lock and 5-second idle-
transaction deadlines. No count-query execution, HTTP/auth/session, Jobs,
other SQL, retries, alternate roles, grants, schema/config changes, cache flush
or fixes.

The collector verifies the reviewed `source_records` AST before connecting,
requires the exact default two-clause population (tenant plus record-kind
subject), and extracts only its matching-count SELECT. The SELECT has one
tenant parameter. It is prefixed with
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, customer identifiers, credentials and exception messages. Estimates
are access-path choices, not runtime or actual row counts.

Temporary files authorized for this pass:

- [Plan collector](../../scripts/diagnostics/plan056_source_records_count_plan.py),
  SHA-256 `ef55dd3213649880db4ef1de9186b457fe7479d8c57e03d58e6065d27c7a7336`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private `/tmp/plan056-source-records-count-plan.XXXXXX`
directory on am-ch-01. Verify hashes and ensure the exact Operations container
destinations `/tmp/plan056_source_records_count_plan.py` and
`/tmp/plan056_coverage_components.py` are absent; confirm `/usr/bin/timeout` is
executable. Copy only these files, verify hashes, then invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_records_count_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output. On
completion or failure, hash-check and remove only these exact files, remove the
empty host directory, and confirm absence. Stop on source mismatch, timeout or
error; no retry. A timeout is incomplete evidence, not a completed timing. If
the connection-closure marker is absent without confirmed process termination,
leave execution unresolved and do not cancel other work.

## Preparation checks

Local extraction produced the exact 354-character SELECT with one placeholder;
its AST fingerprint matches the reviewed value. Python syntax parsing passed.
No external access or application/test changes. **Next:** obtain explicit
approval for this exact plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `source_records` AST gate passed; own backend PID 353898. The
non-ANALYZE plan completed at 16:36:32.326 UTC in 0.034 s, seven nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Aggregate | 1 | 4 | 19978.89 | 19978.90 |
| 1 / 0 | Result | 21944 | 0 | 9083.50 | 19924.03 |
| 2 / 1 | Hash semi-join | 21944 | 0 | 9083.50 | 19924.03 |
| 3 / 2 | Result | 43887 | 1710 | 0.41 | 10042.75 |
| 4 / 3 | Index-only scan, entity_observation_current / uq_obs_current_tenant_observation | 43887 | 24 | 0.41 | 10042.75 |
| 5 / 2 | Hash | 35057 | 24 | 8644.85 | 8644.85 |
| 6 / 5 | Seq scan, source_record_subjects | 35057 | 24 | 0 | 8644.85 |

The query counts all current observations for the tenant with a record-kind
subject. The plan estimates an index-only tenant/observation scan, hash
semi-join against the subject table, then a single aggregate. Total estimated
cost 19978.90 is planner units, not elapsed time; rows are estimates, not actual
counts. Task 5 remains partial. Next frontier: distinct entity-type choices
for the same default population; a separate plan-only scope is prepared in
`docs/records/PLAN-056-source-record-types-plan-execution.md`. No count query,
facet query or fix is approved by this plan check.
