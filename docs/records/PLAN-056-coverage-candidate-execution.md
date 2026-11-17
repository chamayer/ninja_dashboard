# PLAN-056 — Correlated lifecycle candidate plan

Prepared, approved and executed once 2026-11-10. The original Hudu query exceeded its 3-second
server deadline. Its non-ANALYZE plan has a broad lifecycle branch (30,049
estimated rows) below the outer left nested loop, including a per-observation
mapping lookup. This is a concrete plan-shape lead, not measured loop counts.

## Candidate and semantic limits

The [candidate collector](../../scripts/diagnostics/plan056_coverage_candidate.py)
changes only the diagnostic SQL's lifecycle join. The shared lifecycle view is
still the authority (ADR-0011), with the same tenant and observation equality
conditions, now inside a LEFT JOIN LATERAL subquery. OFFSET 0 is an explicit
query-shape fence to test whether planning selects a correlated access path.
It removes no rows; no LIMIT, DISTINCT, new filter or replacement raw Hudu
archive rule is added. The outer projection, Hudu/device/ownership population
and security-barrier views remain identical. No application/view/RLS change.
Actual SQL equivalence and performance still require validation before adoption.
This is a diagnostic candidate, not an approved remedy or implementation slice.

## Exact scope for approval

One non-ANALYZE EXPLAIN of that candidate SELECT on am-ch-01 using the shared
helper and existing Operations runtime role. Reuse the original
[plan-check bounds and redaction](PLAN-056-coverage-plan-execution.md): one
read-only connection, tenant 1, 3-second statement/1-second lock/5-second idle
deadlines, at most 120 whitelisted plan nodes, no expressions or row values.
Source AST mismatch or unexpected original join stops before connecting.
The unchanged [component helper](../../scripts/diagnostics/plan056_coverage_components.py)
is imported for source checks/query extraction only; its main is never called.

No row-query execution, ANALYZE, HTTP/auth, host window, logs, jobs, privileged
inspection, schema/index/config changes or fixes. No retry, alternate query or
role. Approval includes automatic cancellation of only this probe's own
statement on deadline, the diagnostic-only inner process timeout, and temporary
transfer/hash verification/cleanup. This is not permission to ship the candidate.

## Execution after approval

1. Create `/tmp/plan056-coverage-candidate.XXXXXX` through Invoke-DevTool.ps1;
   SCP only the candidate and unchanged component-helper files to that same
   private target and compare full SHA-256. Confirm both
   `/tmp/plan056_coverage_candidate.py` and `/tmp/plan056_coverage_components.py`
   are absent in Operations and `/usr/bin/timeout` is executable. Abort rather
   than overwrite or use a fallback. Copy the two files and verify hashes.
2. Through the helper run once:

   ```sh
   timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_coverage_candidate.py
   ```

   Five-minute overall setup/execution/cleanup budget. Require plan_finished
   for confirmed connection closure. Missing marker without confirmed inner
   termination is incomplete execution, never authorization to retry/cancel
   other work. Preserve sanitized estimates and the explicit candidate variant.
3. Hash-check/remove only those two host and two container files; rmdir the
   empty directory and confirm absence. Container root may remove only the
   root-owned diagnostic files. No wildcard or recursive removal.

Compare with the retained original 21-node plan, without rerunning it. Planner
costs/cardinalities are estimates, not seconds or measured improvement; later
statistics/load may differ. If the candidate plan narrows the lifecycle scan,
that justifies separately reviewed bounded execution/parity validation, not
implementation. If it does not, reject the candidate without a blind replay.

## Local validation

Python import/source fingerprint, exact single join replacement, preserved
projection/equality/view, no LIMIT, Ruff/format and original whitelist/node-bound
checks pass. No application/test files or external access during preparation.
Live candidate planning, results and performance remain unverified. Registry
and whitespace checks pass. Candidate SHA-256:
`e5acf99dea389791dba447de38488d81069dd1af2e9d240ef48811e1e94aeaeb`.
Unchanged helper SHA-256:
`39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.
## Execution outcome — 2026-11-10

Source gates passed. One non-ANALYZE candidate plan completed in 0.049 s at
15:07:04.983 UTC, own backend 349442. All 21 nodes returned; no truncation.
plan_finished confirmed connection closure; exit 0, no retries or process
deadline. Both files hash-verified before execution/removal; exact container/
host files and empty directory removed, absence confirmed. No row-query execution
or application change. Container root was used only for diagnostic cleanup.

Compared with the [original plan](PLAN-056-coverage-plan-execution.md#execution-outcome--2026-11-10),
nodes 2–9 and 18–20 retain their original types, parents, costs, rows and widths.
Changed nodes are below. All nodes remain parallel-aware=false; index scans are
forward. Costs/rows/widths are estimates, never actual timings/loops.

| Node / parent | Type / object | Rows | Width | Startup cost | Total cost |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 / — | Result | 1 | 82 | 507.39 | 75029.22 |
| 1 / 0 | Left nested loop | 1 | 113 | 507.39 | 75029.22 |
| 10 / 1 | Subquery scan, lifecycle | 1 | 32 | 1.86 | 19.13 |
| 11 / 10 | Result | 1 | 924 | 1.86 | 19.12 |
| 12 / 11 | Left nested loop | 1 | 66 | 1.86 | 19.12 |
| 13 / 12 | Inner nested loop | 1 | 691 | 0.56 | 17.80 |
| 14 / 13 | Inner nested loop | 1 | 691 | 0.42 | 9.52 |
| 15 / 14 | Index scan, entity_observation_current / entity_observation_current_pkey | 1 | 713 | 0.42 | 8.44 |
| 16 / 14 | Seq scan, source_instances | 1 | 26 | 0 | 1.06 |
| 17 / 13 | Index-only scan, sources / sources_pkey | 1 | 2 | 0.14 | 8.16 |

The broad lifecycle scan is replaced by a primary-key lookup with a one-row
estimate. Its subtree cost falls from 85,625.27 to 19.13; total query cost from
161,011.33 to 75,029.22. The Hudu population/JSON branch is unchanged and still
accounts for most estimated cost. These are access-path improvements in the
planner, not measured execution gains or proven result parity. The query has
not been adopted. Next: separately approved
[bounded execution and sampled parity](PLAN-056-coverage-validation-execution.md).
