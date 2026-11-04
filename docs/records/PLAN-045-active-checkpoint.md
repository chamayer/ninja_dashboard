# PLAN-045 — emergency ownership backlog repair

## Goal and authorization

User authorized stopping all Ninja jobs and fixing the production emergency.
Ingest and Jobs were stopped at approximately 23:01 UTC on 2026-11-04.
Operations and Postgres remain healthy. Do not restart job services until a
reviewed repair is ready. Commit/push remain subject to separate approval.

## Confirmed state

4,254 live ownership rows remain dirty. The resolver held the exclusive tenant
guard from 22:29:55 for more than 30 minutes, alternating name-candidate queries
and resolver association calls. Four other sessions waited 25–30 minutes.
Ownership reconciliation runs after identity resolution and promotion, so it
had not been reached. After stopping both services, no holder or waiter remained.
Job ledger running states remain interrupted; do not forge terminal results.

## Scope and design

Bound resolver mutation transactions and re-read each selected record batch
under the guard. Name each batch's changed Computers before commit. Reconcile
ownership before expensive matching and again after association changes.
Bound promotion transactions as well; preserve per-record identity decisions,
source/tenant filtering, and the sole association writer. Keep 0.144.2's
coordination instead of removing deadlock protection.

## Validation and next action

Use small local synthetic tests for batching, re-reading changed/attached
records, per-batch naming, deferred ownership, failure propagation, and policy
behavior. Do not run full local evaluators or performance workloads.
Implemented on origin/master in `.work/plan045-emergency`, release 0.144.3.
Matching and promotion use at most ten records per transaction and re-read
current presence/association/evidence before mutations. Naming remains atomic
with each batch. Earlier committed batches survive a later failure; that failure
escapes matching to the Job. The dirty-only final drain avoids a second full
fleet sweep. Current guard protection is retained; no migration or retry added.
74 focused checks pass, including PostgreSQL re-read and deadlock regressions.
Promotion failures escape to the Job instead of being logged as successful work.
Ruff, syntax, registry and diff checks pass. No performance guarantee is inferred
from synthetic tests. User requested finishing this as an explicit goal with no
additional heavy testing or broad design work; completed checks are sufficient
for the scoped implementation review.
Production remains stopped; no commit, push, deployment or restart yet.
Next complete checks, obtain release commit/push approval, then verify controlled
recovery and backlog drain. Investigate individual query costs afterward.
