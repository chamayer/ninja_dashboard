# PLAN-056 — Source Records entity-type facet plan check

Prepared 2026-11-10 after the default Source Records count plan. This is the
next unmeasured read in the previously reviewed reader frontier.

## Exact scope for approval

One non-ANALYZE EXPLAIN of the exact distinct `observation.entity_type` choices
SELECT from `source_records`, on am-ch-01 through `Invoke-DevTool.ps1`, inside
Operations using the existing runtime database role. One connection, tenant 1,
read-only transaction, 3-second statement, 1-second lock and 5-second idle-
transaction deadlines. The query population is the same default tenant and
record-kind subject scope as the count; no search, source, client or other
filters. No facet-query execution, HTTP/auth/session, Jobs, other SQL, retries,
alternate roles, grants, schema/config changes, cache flush or fixes.

The collector verifies the reviewed `source_records` AST and exact selected
SQL/tenant parameter before connecting. It issues only
`EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output is
capped at 120 plan nodes and excludes expressions, predicates, SQL, parameters,
row values, customer identifiers, credentials and exception messages. Plan
estimates are not actual counts or elapsed time.

Temporary files within this scope:

- [Plan collector](../../scripts/diagnostics/plan056_source_record_types_plan.py),
  SHA-256 `8c15020b9f056f930d53c48b42a5236db8370ab62c309b66b15234f7c6443ba1`.
- [Unchanged plan helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private
`/tmp/plan056-source-record-types-plan.XXXXXX` on am-ch-01. Verify hashes and
ensure exact Operations destinations `/tmp/plan056_source_record_types_plan.py`
and `/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_source_record_types_plan.py
```

Five-minute setup/execution/cleanup budget. Preserve only sanitized output.
After confirmed completion or failure, hash-check and remove only these exact
container and host copies, remove the empty host directory, and confirm
absence. Stop on mismatch, timeout or error; no retry. If the connection-closure
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks

Local extraction matched the reviewed AST and exact 587-character SELECT with
one tenant placeholder. Python syntax parsing passed. No external access or
application/test changes. **Next:** obtain explicit approval for this exact
plan-only check.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through `Invoke-DevTool.ps1` on am-ch-01.
The deployed `source_records` AST gate passed; own backend PID 354056. The
non-ANALYZE plan completed at 16:39:56.980 UTC in 0.102 s, nine nodes, no
truncation. `plan_finished` confirmed status 0 and connection closure. Host and
container hashes matched the reviewed collector and unchanged helper before
removal; exact copies and the empty host directory were removed and absence
confirmed.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Sort | 200 | 12 | 170978.46 | 170978.96 |
| 1 / 0 | Aggregate | 200 | 12 | 170968.81 | 170970.81 |
| 2 / 1 | Result | 41254 | 12 | 14587.19 | 170865.68 |
| 3 / 2 | Hash semi-join | 41254 | 12 | 14587.19 | 170865.68 |
| 4 / 3 | Result | 82507 | 1544 | 5504.11 | 160282.00 |
| 5 / 4 | Bitmap heap scan, entity_observation_current | 82507 | 36 | 5504.11 | 160282.00 |
| 6 / 5 | Bitmap index scan, uq_obs_current_tenant_observation | 82507 | 0 | 0 | 5483.22 |
| 7 / 3 | Hash | 35057 | 24 | 8644.85 | 8644.85 |
| 8 / 7 | Seq scan, source_record_subjects | 35057 | 24 | 0 | 8644.85 |

The plan estimates scanning tenant observations and record subjects, then
distinct aggregation and sorting. The index-only scan used for the count is
not available to supply `entity_type`, so this plan estimates a bitmap heap
scan. Total cost 170978.96 versus 19978.90 for the count is a planner-cost
difference only; it is not an elapsed-time ratio or measured contribution.
Rows remain estimates. Task 5 is incomplete. Next: prepare the analogous
non-ANALYZE plan for distinct nonnull source-layout choices; no layout query
execution or remedy is approved.
