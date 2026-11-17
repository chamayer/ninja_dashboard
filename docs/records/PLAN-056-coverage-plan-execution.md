# PLAN-056 — Hudu Coverage query-plan check

Prepared, approved and executed once 2026-11-10. The component probe completed
stored requirements in 0.604 s, then the Hudu inventory/lifecycle query hit the
3-second server deadline. This check follows that measured component, not an
unattributed HTTP request. Task 4 remains open.

## Exact scope for approval

One non-ANALYZE EXPLAIN of that same Hudu SELECT on am-ch-01, through the shared
helper inside Operations using the existing runtime database role. One
connection, tenant 1, read-only transaction, 3-second statement/1-second lock/
5-second idle deadlines. No row-query execution, HTTP/auth/session, jobs,
privileged inspection, grants, configuration changes, cache flush or fixes.
No retries, alternate roles, additional queries or EXPLAIN ANALYZE.

Transfer/hash-check/cleanup only these two reviewed files and a fresh host
directory:

- [Plan collector](../../scripts/diagnostics/plan056_coverage_plan.py).
- [Unchanged component helper](../../scripts/diagnostics/plan056_coverage_components.py),
  imported only for source fingerprint checks, exact query extraction and
  aggregate emission. Its query-executing main is not called.

The collector verifies the same deployed Coverage/selector AST signatures
before connecting, selects only component 2 (`hudu_inventory_lifecycle`) and
issues `EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE)` without ANALYZE. Output
is capped at 120 plan nodes with parent indices and an explicit truncation
flag. Only node/join/scan type, schema/relation/alias/index/function/CTE names,
estimated startup/total costs, rows/width and parallel-awareness are emitted.
No expressions, filters, outputs, conditions, SQL text, row values, business
identifiers, credentials or exception messages. Also emits own backend PID,
UTC, elapsed time, SQLSTATE on failure and connection-closure marker.

Planner estimates describe access choices, not actual timings/loops or a proof
of runtime causation. Planner work still has the normal server deadline; its
automatic cancellation applies only to this probe's own statement. An inner
60-second timeout (kill after 5 more) applies only to the diagnostic process.
Approval includes those bounds and temporary diagnostic transfer/cleanup.

## Execution after approval

1. Via Invoke-DevTool.ps1 create `/tmp/plan056-coverage-plan.XXXXXX`; SCP only
   the two listed files to that same private target. Compare full SHA-256.
   Confirm `/tmp/plan056_coverage_plan.py` and
   `/tmp/plan056_coverage_components.py` are absent in Operations and
   `/usr/bin/timeout` is executable. Abort rather than overwrite/fallback.
   Copy both files to those exact container destinations and verify hashes.
2. Via the helper run once:

   ```sh
   timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_coverage_plan.py
   ```

   Overall setup/execution/cleanup budget: five minutes. A plan_finished marker
   confirms connection closure. No marker and no confirmed inner-timeout
   termination means execution remains incomplete; do not rerun or cancel
   another backend. Report failure and retain cleanup pending if needed.
3. Preserve sanitized aggregate plan/results; hash-check/remove only the two
   container and two host copies, then rmdir the empty directory and confirm
   absence. Container root is permitted only for those root-owned temporary
   files. No recursive/wildcard removal or application-file changes.

## Local findings and interpretation

Repository migrations 0149 and 0158 define both joined views as security-barrier
views. Hudu inventory projects JSON fields and a relayed-card existence check;
the lifecycle view has a lateral per-observation lifecycle-mapping lookup with
JSON comparison, ordering and LIMIT 1. These are code-level leads, not verified
installed definitions or demonstrated cost shares. The plan should show which
structures/access paths survive planning. Do not assume an index, barrier
change, JSON rewrite or summary is the remedy before reviewing evidence and
tenant/security/correctness contracts.

Local AST/import/exact component checks, Ruff/format, whitelist redaction,
parent linkage and 120-node truncation checks pass. No test files or application
edits. Registry/whitespace checks pass. Live planning remains unverified.
Reviewed plan-collector SHA-256:
`fecf58b3a24016fe33b753cca6a1d5d59ff3aae227723c77f0c6f76b9d50e00f`.
Unchanged component-helper SHA-256:
`39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.
## Execution outcome — 2026-11-10

Deployed AST gates passed; own backend 349180. The single non-ANALYZE EXPLAIN
completed at 15:01:14.472 UTC in 0.141 s. All 21 nodes were returned, no
truncation. plan_finished confirmed connection closure; exit 0, no retry or
process deadline. Both host/container copies matched reviewed hashes before
execution/removal; exact files and empty host directory removed, absence
confirmed. Container root was used only for diagnostic cleanup.

Costs below are planner units, not milliseconds. Rows/width are estimates,
not returned counts/actual loops. Objects are schema/index/function names.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Result | 150 | 82 | 507.66 | 161011.33 |
| 1 / 0 | Left nested loop | 150 | 113 | 507.66 | 161010.95 |
| 2 / 1 | Inner nested loop | 1 | 89 | 505.51 | 75010.05 |
| 3 / 2 | Inner hash join | 19 | 129 | 505.23 | 74976.09 |
| 4 / 3 | Result | 4722 | 218 | 0.67 | 74399.52 |
| 5 / 4 | Index scan, entity_observation_current / idx_obs_current_active | 4722 | 724 | 0.67 | 74221.49 |
| 6 / 4 | SubPlan function scan, jsonb_array_elements | 99 | 0 | 0.01 | 2.01 |
| 7 / 3 | Hash | 5781 | 40 | 417.84 | 417.84 |
| 8 / 7 | Seq scan, computer_client_ownership | 5781 | 40 | 0 | 417.84 |
| 9 / 2 | Index scan, devices / devices_pkey | 1 | 40 | 0.28 | 1.77 |
| 10 / 1 | Result, lifecycle side | 30049 | 56 | 2.13 | 85625.27 |
| 11 / 10 | Result | 30049 | 924 | 2.11 | 85324.76 |
| 12 / 11 | Left nested loop | 30049 | 90 | 2.11 | 85324.76 |
| 13 / 12 | Inner nested loop | 30049 | 715 | 0.81 | 53397.44 |
| 14 / 13 | Inner nested loop | 1 | 26 | 0.14 | 10.60 |
| 15 / 14 | Seq scan, source_instances | 1 | 26 | 0 | 2.31 |
| 16 / 14 | Index-only scan, sources / sources_pkey | 1 | 2 | 0.14 | 8.16 |
| 17 / 13 | Index scan, entity_observation_current / uq_obs_current_stable_identity | 21464 | 729 | 0.67 | 53172.20 |
| 18 / 12 | Limit | 1 | 79 | 1.04 | 1.04 |
| 19 / 18 | Sort | 1 | 79 | 1.04 | 1.04 |
| 20 / 19 | Seq scan, source_record_lifecycle_mappings | 1 | 79 | 0 | 1.03 |

All nodes were parallel-aware=false; index scans were forward. Schema is
operations except pg_catalog.jsonb_array_elements. The broad lifecycle branch
under the top left nested loop is a concrete access-path lead; actual outer
cardinality, repeated work and cost shares remain unmeasured. Do not infer a
30,049-row actual scan or multiply estimates into measured work.

The shared editable lifecycle policy must remain authoritative; raw Hudu
archived is not a safe replacement (ADR-0011). Next: the separately gated
[correlated candidate plan](PLAN-056-coverage-candidate-execution.md), preserving
that authority and testing a narrower lookup without executing the row query.
