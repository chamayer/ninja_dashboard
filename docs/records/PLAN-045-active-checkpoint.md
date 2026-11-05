# PLAN-045 — source-derived Computer ownership (completed)

## Goal

Keep source-derived Computer ownership current without making source writes
wait for the identity resolver or long ownership transactions. Preserve the
existing tenant findings guard and atomic Computer ownership projection.

## Design delivered

- Dirty ownership reconciliation is a coalesced Jobs workflow triggered after
  source writes. A 10-minute catch-up handles later resolver invalidations; a
  daily low-priority full sweep provides anti-entropy.
- Each Computer is projected in its own guarded transaction. Ownership and
  dependent client-scope updates stay atomic, while other writers can acquire
  the guard between Computers.
- Platform health loads active Jobs failure findings once and matches unmet
  dependencies in memory. It no longer scans `admin_findings` once per
  dependency while holding the tenant guard.

No schema migration or new queue framework was added. The tenant-wide findings
guard remains intentional; this work bounds the two observed long holders while
preserving existing lock order and consistency rules.

## Production evidence — 2026-11-05

- Release 0.144.7 (`e5dbaffb`) deployed one-Computer ownership transactions.
- Release 0.144.8 (`60ddb296`) deployed the single-query Jobs finding lookup.
- SentinelOne source refresh completed on 0.144.8 and wrote 4,487 source
  observations. Its ownership successor depended only on that source run,
  completed, and did not wait for the resolver.
- The preceding dirty-only ownership run completed with 31 resolved and 1
  conflict. The successor completed afterward. Live dirty ownership was 0,
  including 0 older than 30 minutes.
- Platform health completed in 17 seconds on 0.144.8; the preceding run on
  0.144.7 took 6 minutes 23 seconds. A live guard snapshot during the new
  lookup showed one query at about 8 seconds and no waiting writers.
- Ingest, Operations, and Jobs worker were healthy at final verification. No
  worker deadlocks appeared in the preceding 15 minutes.

## Validation and limitations

Three focused ownership `unittest` cases passed. Python compilation, Ruff,
plan-registry validation (52 entries), and `git diff --check` passed. The
platform-finding unit test could not run locally because `psycopg` is absent;
the pytest runner is also unavailable. Production execution of the scheduled
platform-health job validated the changed path. No full-fleet local run was
performed.

The Jobs worker restarted once after a separate `jobs_one_executing_run`
unique-key violation while claiming an ownership run. It recovered, completed
the owner successor, and is healthy. Track investigation of that queue-claim
race separately in the repository backlog; it did not leave ownership dirty.
