# PLAN-056 — Sources record-count plan check

Prepared 2026-11-10 after reconciling the handoff and Git state. This follows
the `sources_record_counts` timeout in the [read attribution pass](PLAN-056-source-reads-execution.md).

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact `sources_status` SELECT from
`operations.v_source_instance_record_counts`, on am-ch-01 through
`Invoke-DevTool.ps1`, inside Operations using the existing runtime database
role. One connection, tenant 1, read-only transaction, 3-second statement,
1-second lock and 5-second idle-transaction deadlines. No execution of the row
query, HTTP/auth/session, Jobs, other SQL, retries, alternate roles, grants,
schema/config changes, cache flush or fixes.

Files transferred and removed only within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_sources_counts_plan.py),
  initial SHA-256 `3be222c1b2950cd8809937f6735e759d268c7c8bdadab93022a6b1c882fbd86`.
- [Unchanged component helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

The collector verifies the reviewed `sources_status` AST fingerprint before
connecting and extracts only the SELECT naming the record-count view. Its
output is limited to own backend PID, elapsed time, bounded plan-node metadata,
SQLSTATE/error class and connection-closure marker. It excludes SQL text,
expressions, filters, row values, customer identifiers, credentials and error
messages. Plan estimates describe planner choices, not measured execution.

After approval, use a fresh private `/tmp/plan056-sources-counts-plan.XXXXXX`
host directory. Verify source and helper hashes, ensure exact destinations
`/tmp/plan056_sources_counts_plan.py` and
`/tmp/plan056_coverage_components.py` are absent in Operations, and confirm
`/usr/bin/timeout` is executable. Copy only those files and verify hashes.
Invoke once with:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_sources_counts_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve sanitized output. Hash
check and remove only those exact host/container files, remove the now-empty
host directory and confirm absence. Stop on source mismatch, timeout or error;
no retry. A timeout is incomplete evidence, not a completed timing. If the
connection-closure marker is absent without confirmed process termination,
leave execution unresolved and do not cancel other work.

## Preparation checks

Python 3.12 syntax compilation passed. Both file hashes recorded above. No
external access or app/test changes. Live source compatibility and plan remain
unverified.

## First approved invocation outcome — 2026-11-10

The approved invocation returned `setup_failed` with error class `ValueError`
and no plan or connection-closure marker. Local reproduction isolated the
preconnection extractor guard: the actual `cur.execute` call has the tenant
parameter tuple as its second argument. No SQL was issued. The bounded command
ended; exact container files were removed as root after hash verification, and
both exact remote host copies plus the empty directory were removed and absence
confirmed. No retry occurred.

The extractor now explicitly verifies the second argument is the one-element
`tenant_id` tuple. Local extraction yields the exact 345-character SELECT with
one placeholder; syntax parsing passes. Corrected collector SHA-256:
`2ad9b78b0a88e5b72b806096c916150808434cee218e70dfdeca5e11df5670f4`.
Live source compatibility and plan remain unverified. **Next:** obtain fresh
approval for one invocation using the corrected collector and the same bounded
scope. The prior approval covered only the failed invocation; no retry was
authorized under that approval.

## Corrected approved invocation — 2026-11-10

After fresh approval, one invocation ran through `Invoke-DevTool.ps1` on
am-ch-01. The deployed `sources_status` AST gate passed; own backend PID
352552. The non-ANALYZE plan completed at 16:06:57.460 UTC in 0.084 s, with
nine nodes and no truncation. `plan_finished` confirmed status 0 and connection
closure. The exact host/container hashes matched the corrected collector
(`2ad9b78b0a88e5b72b806096c916150808434cee218e70dfdeca5e11df5670f4`) and
unchanged helper before removal; exact copies and the empty host directory were
removed and absence confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Sort | 616 | 238 | 120919.83 | 120921.37 |
| 1 / 0 | Subquery Scan, v_source_instance_record_counts | 616 | 238 | 120878.96 | 120891.28 |
| 2 / 1 | Aggregate | 616 | 246 | 120878.96 | 120885.12 |
| 3 / 2 | Result | 28577 | 223 | 5194.55 | 120378.87 |
| 4 / 3 | Hash join | 28577 | 223 | 5194.55 | 120378.87 |
| 5 / 4 | Bitmap heap scan, entity_observation_current | 28577 | 45 | 5193.05 | 120273.45 |
| 6 / 5 | Bitmap index scan, uq_obs_current_tenant_observation | 42865 | 0 | 0 | 5185.90 |
| 7 / 4 | Hash | 11 | 356 | 1.11 | 1.11 |
| 8 / 7 | Seq scan, entity_types | 11 | 356 | 0 | 1.11 |

The top estimated cost is 120921.37 planner units, not time. Estimated rows
are not actual cardinalities or loop counts. The tenant/observation index,
heap access, entity-type hash join, aggregate and sort are visible. The
migration-defined view also calls `operations.is_companion_stream` for each
candidate observation; that SQL SECURITY DEFINER function probes companion
configuration through source instances. Its execution count/cost is not
visible in this plan, so this is a code-level lead rather than measured cause.
Do not infer runtime improvement or select an index/cache/remodeling remedy
from this plan alone.

Task 5 remains partial. Next: use the local call-path review to decide whether
a separately bounded diagnostic can attribute `is_companion_stream` safely and
usefully. No repeat, ANALYZE, row execution or fix is approved.

## Local view and consumer review — 2026-11-10

Migration 0397 defines this as a tenant-wide grouped view: it filters by
`current_tenant_id()`, joins 11 entity types, excludes companion observations
through `is_companion_stream`, and groups by source instance/type/class. The
selected reader adds no source-instance restriction; it sorts the grouped
results in SQL, then groups those rows by source instance in Python. Migration
0103 defines the observed unique `(tenant_id, observation_id)` index used by
the plan. The view's SQL function performs a companion-stream lookup via
`source_instances` and companion configuration. Its per-row call count and
runtime share are unavailable. The EXPLAIN's `Result` subtree estimate and
broad tenant bitmap scan are consistent with this shape, but cannot prove the
function is the dominant cost. No remedy selected; next determine whether a
specific bounded diagnostic can attribute its actual share, then assess safe
alternatives before any implementation proposal.

PostgreSQL function counters were considered for that gap. The previous
resource capture did not include `track_functions`; `pg_stat_statements` was
not installed. Even when enabled, `pg_stat_user_functions` reports cumulative
function calls/time, not per-request attribution, and there is no baseline for
the timed-out Sources statement. No new instrumentation is justified for this
diagnostic stage. Continue with the next named read frontier, the default
Source Records count; its bounded plan-only protocol is prepared separately.
