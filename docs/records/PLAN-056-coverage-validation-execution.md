# PLAN-056 — Bounded candidate execution and sampled parity

Prepared, approved and executed once 2026-11-10. The candidate plan replaces the broad lifecycle
branch with a primary-key observation lookup; this justifies execution/parity
validation, not a fix or deployment. Task 4 remains open.

## Exact scope for approval

One pass on am-ch-01 through Invoke-DevTool.ps1, inside Operations using the
existing runtime database role. At most four SELECTs on one connection in one
REPEATABLE READ, READ ONLY transaction, tenant 1. Each statement has a 3-second
server deadline, 1-second lock deadline and 5-second idle-transaction deadline.
Stop on first SQL failure, empty sample, processing bound or unequal result;
no retry, further SELECT or role fallback. Approval includes cancellation only
of the probe's own statement on its server deadline and timeout termination
only of the explicitly launched diagnostic process.

| Order | SELECT scope and purpose |
| --- | --- |
| 1 | At most three distinct Hudu observation IDs in stable UUID order, using the original Hudu/device/ownership population before lifecycle join. IDs remain in memory. |
| 2 | Original query restricted to exactly those IDs. |
| 3 | Candidate query restricted to exactly those IDs; compare complete result multisets in memory within the same snapshot. |
| 4 | Only after nonempty sampled parity passes: one full candidate SELECT, count/discard rows without printing values. |

The full original query is not rerun. There is no timing loop, HTTP/login,
session mutation, job, cache flush, host/log observation, privileged inspection,
schema/index/config change or application edit. Full candidate execution is
explicitly included; it reads the same fleet-scoped Hudu population as the page,
under the existing security-barrier views and runtime RLS. Its output is not
installed or persisted as a read model.

## Exact artifacts and safeguards

- [Validation collector](../../scripts/diagnostics/plan056_coverage_validate.py).
- [Unchanged candidate helper](../../scripts/diagnostics/plan056_coverage_candidate.py),
  imported only for the exact join transformation; its EXPLAIN main is not run.
- [Unchanged component helper](../../scripts/diagnostics/plan056_coverage_components.py),
  imported for source gates, query extraction and aggregate emission only.

Deployed Coverage/lifecycle-selector AST signatures must match before connecting.
The original join must occur exactly once. Sample selection retains original
Hudu/device/ownership/current-Computer predicates; sample restriction adds only
the three selected IDs to both queries. No IDs, names, hostnames, customer data,
query text, result values, credentials or exception messages leave the collector.
Only own backend PID, UTC, phase, elapsed time, aggregate counts, parity boolean,
SQLSTATE and connection-closure marker are returned. Counter comparison preserves
duplicate multiplicity. Sample result processing is capped at 4,096 rows; full
candidate at 100,000 rows, batches discarded. These are client guards, not SQL
memory limits; the server statement deadline remains the execution bound.

## Execution after approval

1. Create `/tmp/plan056-coverage-validation.XXXXXX` through the shared helper.
   SCP only the three reviewed files above to the same private target and
   compare full SHA-256. Confirm their exact `/tmp/` container destinations
   are absent and `/usr/bin/timeout` is executable; abort rather than overwrite
   or fall back. Copy the three files into Operations and verify hashes.
2. Through the helper run once:

   ```sh
   timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_coverage_validate.py
   ```

   Five-minute overall setup/execution/cleanup budget. Require
   validation_finished for confirmed connection closure. Incomplete outer
   execution without closure/confirmed inner termination is not a retry or
   other-work cancellation approval; report it and retain cleanup pending
   where necessary. The inner 60-second/5-second kill bound applies only to
   this diagnostic process, not Gunicorn or a Jobs worker.
3. Preserve aggregates; hash-check/remove only the three host and three container
   copies, then rmdir the empty directory and confirm absence. Container root
   may remove only the root-owned diagnostic files. No recursive/wildcard removal.

## Interpretation and remaining validation

Three observations are a sampled result check, not fleet-wide parity, synthetic
edge-case coverage, ordinary-user/other-tenant validation, or page acceptance.
An empty sample establishes nothing and stops. The full candidate timing is
one current observation, not a comparable-load speedup over the earlier timeout.
If it times out, record that result and stop. If it completes with sampled
parity, retain it as a candidate for the later requirements/remedy review;
do not implement, claim all Coverage work is fast or close platform recovery.

Local source/query extraction, population/sample bound, Ruff/format and in-memory
success/multiset-mismatch/timeout-stop/snapshot-setup/redaction/connection-exit
checks pass. No test files or application edits. Live sample/full execution is
unverified. Registry/whitespace checks pass. Validation collector SHA-256:
`cfb3dc6c2b36bd9a326f51ec7e06b5e05e606d65256dd847ca4463e9e81af836`.
Helper hashes remain those recorded in the candidate/component execution reviews.
## Execution outcome — 2026-11-10

Source gates passed. One runtime-role connection, backend 349843, one read-only
repeatable snapshot. All four SELECTs completed within their server deadlines:

| Phase | Elapsed | Rows |
| --- | ---: | ---: |
| Select three eligible observation IDs | 0.167 s | 3 |
| Original restricted to those IDs | 1.602 s | 3 |
| Candidate restricted to those IDs | 0.006 s | 3 |
| Full candidate after sampled parity | 0.374 s | 4,873 |

Full six-column result multisets matched on the three observations, preserving
duplicate multiplicity. No identifiers or row values were returned. All reads
ran 15:15:58.537–15:16:00.687 UTC; validation_finished confirmed connection
closure, status/exit 0, no wrapper timeout, retry or SQL failure. All three
host/container files matched reviewed hashes before execution/removal; exact
files and empty host directory removed, absence confirmed. Container root
was used only for diagnostic cleanup. No app/config/schema changes or HTTP.

The full candidate is now observed to complete under three seconds in this
window. No full-original result comparison, fleet parity, edge-case coverage,
other-role/tenant validation or whole-page acceptance is established. The
restricted original ran before the candidate, so cache/order and current load
prevent turning their timings into a general speedup ratio. The earlier full
original timed out in another window. Retain the candidate for task 5 attribution
and later requirements/remedy review; adoption remains unapproved.
