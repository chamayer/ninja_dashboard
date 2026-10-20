# Unified Jobs WP0.3 measurements

Date: 2026-09-24

Status: partial evidence for WP0.3; not a completed capacity or timeout audit.
The active-duplicate and duration queries were rerun with lifecycle boundaries
explicit. The retained sample below predates the follow-up described at the
end and was not collected in one consistent database snapshot. Historical
per-invocation linkage remains unavailable where the existing schema stores
a blank `run_log_kind`.

These are aggregate, read-only measurements collected through the approved
`am-ch-01` helper. No identifiers, payloads, credentials, or customer data
are included.

## Service sample

The relevant production containers were healthy at collection time:

- `operations-ingest`
- `ninja-operations`
- `ninja-postgres`

## Durable operator Jobs

| Status/lane | Count |
| --- | ---: |
| Cancelled / software | 1 |
| Completed / collection | 229 |
| Completed / evaluation | 49 |
| Completed / intelligence | 13 |
| Completed / service | 1 |
| Failed / evaluation | 3 |
| Queued / evaluation | 1 |
| Queued / intelligence | 5 |
| Running / software | 1 |
| Stalled / software | 5 |

One running row exceeded 90 minutes. Five rows were terminal `stalled`; three
rows were `failed`. No duplicate `(tenant, job_key)` groups existed when
limited to active `queued`/`running` rows. Request age is not execution
duration because it includes time spent waiting before `started_at`.

Completed operator duration by job key (`count | median | p95 | maximum`,
seconds):

| Job key | Duration sample |
| --- | ---: |
| agent-compliance-evaluate | 3 \| 17.8 \| 18.9 \| 19.0 |
| agent-observations | 10 \| 241.3 \| 338.4 \| 354.0 |
| documentation-observations | 4 \| 151.5 \| 156.9 \| 157.8 |
| intel-abusech | 1 \| 95.7 \| 95.7 \| 95.7 |
| intel-kev | 9 \| 1.9 \| 2.3 \| 2.5 |
| intel-matcher | 1 \| 866.7 \| 866.7 \| 866.7 |
| intel-nvd | 1 \| 58.5 \| 58.5 \| 58.5 |
| intel-otx | 1 \| 4.3 \| 4.3 \| 4.3 |
| patches | 18 \| 399.7 \| 526.6 \| 531.7 |
| platform-evaluate | 3 \| 465.7 \| 471.9 \| 472.6 |
| resolver | 23 \| 54.6 \| 70.1 \| 70.5 |
| retention-history | 1 \| 0.7 \| 0.7 \| 0.7 |
| software-queue-drain | 217 \| 30.4 \| 36.0 \| 39.6 |

These are the 13 emitted completed-job groups, totaling 292 runs. Definitions
without completed runs have no duration estimate. Small sample counts and the
exclusion of unfinished work prevent using these maxima as timeout guarantees.

## Linked domain queues and diagnostic history

| Measure | Result |
| --- | ---: |
| Source-demand done | 71 |
| Source-demand failed | 2 |
| Source-action rows in sampled status groups | no grouped rows returned |
| Operations run-log failed | 856 |
| Operations run-log successful | 3,810 |
| Operations run-log completed rows | 4,666 |
| Run-log kinds unmatched through `operator_job_runs.run_log_kind` | 9 kinds / 4,666 rows; execution coverage undetermined |
| Duplicate pending source-demand groups | 0 groups / 0 excess rows |

The source-demand table had no `processing` rows at collection time, so no
source processing-age buckets were emitted. The source-action status query
returned no grouped rows, and its expired-lease count was 0.

The runtime enqueue paths in `ingest/operator_job_queue.py` and
`operations/apps/core/views.py` do not populate `run_log_kind`; migration
0178 gives it an empty default. The unmatched result is a correlation gap,
not proof that the diagnostic rows represent work outside the durable queue.
Per-invocation historical linkage cannot be invented from matching names.

## Lock and failure indicators

- `pg_stat_database.deadlocks` reported 17 cumulative deadlocks for the
  database. This is a cumulative server statistic, not a WP0-period rate.
- The activity sample contained client, timeout, and non-waiting sessions;
  no ungranted lock rows were returned by the aggregate check.
- The run-log failure count is diagnostic evidence only and is not treated as
  the Job lifecycle authority.

## Capacity assumptions confirmed from code

- The ingest PostgreSQL pool is configured with `max_size=4`.
- The current operator queue uses a shared two-worker semaphore.
- Five named worker lanes exist: collection, evaluation, software,
  intelligence, and service.
- Operator leases are 90 minutes with 30-second heartbeat updates.

These measurements establish the current baseline only. They do not choose
future lane capacities, resource keys, timeout policy, or worker topology;
those remain WP1/ADR-0024 decisions. The pool limit above is confirmed from
local code defaults, not deployed configuration. Historical run-log linkage
is unavailable because Job rows have blank kind linkage. An empty grouped
source-action result means no rows were returned; it is not evidence that
their status fields are blank.

## Reproducible follow-up and validation limits

`jobs-measure.sql` uses a repeatable-read/read-only transaction, a 15-second
timeout per statement, a two-second lock timeout, stop-on-error, and rollback.
It includes all three software queues, active-only duplicate checks, actual
started-to-completed durations, stored failure-wording classifications, and
tenant-aware linkage checks. Source log keys are reduced to families before
output. Failure wording is not proof of a timed-out or killed process.

An invocation began at 2026-09-24 13:57:28 UTC. Captured output reached
operator status and zero active duplicate groups, but no completion or rollback
output was obtained before the user interrupted work. On resumption the local
tool session was no longer available. Do not claim that this script completed
or that its remote session state was verified. Its later statements and the
full follow-up result remain unvalidated; no rerun was made during drafting.

Remaining evidence: full handler execution-path coverage, timeout causes,
unfinished/uncertain executions, deployed connection/process capacity, and
verified domain-row ownership. The samples above inform the design review
but do not close these prerequisites.
