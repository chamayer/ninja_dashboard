# Jobs worker topology review

Status: proposed only; no Compose, Dockerfile, entrypoint, or service change.

## Observed packaging boundary

`ingest.Dockerfile` already copies `ingest/`, `sql/`, and `shared/` into the
image. It runs `python -m ingest.main`, exposes port 8090, and uses an HTTP
healthcheck. The root Compose `ingest` service builds that image, mounts the
private environment directory read-only, publishes 8090, and waits for
Postgres health. `operations.Dockerfile` independently copies `shared/`, so a
future shared declarative registry is package-visible to both images without
a new bind mount.

The current ingest process owns HTTP, APScheduler, migration/bootstrap work,
and in-process queue threads together. Starting a second copy of that command
would duplicate HTTP binding, schedule production, startup catch-up, and
bootstrap side effects. It is not a worker topology.

## Proposed service shape

After the reviewed schema/registry activation—not in preparation—retain one
`ingest` service as HTTP and schedule-request producer. Add one or more worker
services from the same `ingest.Dockerfile`, each using a new explicit worker
module command. A worker module must not start HTTP, APScheduler, migrations,
Metabase bootstrap, or legacy startup catch-up. It should only validate its
registry/schema revision, register a unique supervisor incarnation, supervise
the lane(s) it is assigned, and expose a bounded liveness/readiness probe.

Workers need no public ports. The existing HTTP healthcheck is invalid for a
worker: Compose must override it with a worker-specific process/readiness
probe. They need the same read-only environment mount and Postgres health
dependency as ingest. Dockerfile copying `shared/` already satisfies the
registry package requirement; a new worker module must be included under
`ingest/`, which the current Dockerfile recursively copies.

Do not select worker replica counts, lane allocations, child concurrency,
memory limits, Postgres pool sizes, or restart grace periods yet. The current
two-slot in-process semaphore, static code default of pool size four, and the
partial duration sample are insufficient evidence for those choices. Each
supervisor and child has database-connection cost, so deployment admission
requires a reviewed total connection budget including HTTP, Operations,
Postgres maintenance, scheduler control, supervisors, and children.

## Activation and rollback boundary

The approved rollout direction is a quiesced cutover. The activation migration
and deployment must: stop legacy direct writers/pollers from claiming
converted families; drain or retain old pending work under a per-family
procedure; verify no old child remains; fence legacy raw transitions; activate
matching registry/schema revisions; then start compatible request producers
and workers. Until that point, Compose has no worker service change.

If a rollback is required after converted execution starts, quiesce the new
executors and reconcile every uncertain external mutation before restoring an
older image. Do not remove ledger/alias/event/domain history or simply bring
up the old ingest command while new resource claims can still be held.

## Required focused validation when implemented

1. Image/package inspection proves the worker module and `shared/` registry
   are present in the worker image.
2. A worker readiness mismatch prevents claims but does not make the HTTP
   producer unhealthy.
3. One deliberately blocked child leaves HTTP/scheduling responsive and does
   not consume unrelated lane capacity.
4. Stop/restart confirms fencing: an old supervisor cannot finalize a new
   owner, and an unsafe/uncertain child remains contained.
5. Compose review confirms no worker public port, invalid inherited HTTP
   healthcheck, or worker migration/bootstrap path.

These are future focused checks, not a request to run an integration suite
now. Current topology review is source-only.
