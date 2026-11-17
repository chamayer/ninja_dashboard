# PLAN-056 — Task 3 execution review

Prepared 2026-11-09; not executed. The [protocol](PLAN-056-measurement-protocol.md)
governs. Request authorization for the existing `am-ch-01` SSH profile's
production target: one bounded observation, temporary reviewed script transfer
and cleanup only. No app GET, session, job, deployment, migration, grant,
configuration change or production data mutation is included.

## Reviewed artifacts

- [Database collector](../../scripts/diagnostics/plan056_db_observe.py): nine
  metadata queries, then five bundled samples 15 seconds apart. Uses existing
  Operations runtime credentials without displaying them; no Django setup or
  connection hooks. Read-only connection and transactions; tenant 1, 3-second
  statement/1-second lock/5-second idle limits. Any database error stops the
  collector without retry; output is allowlisted JSON or error class/SQLSTATE.
- [Host collector](../../scripts/diagnostics/plan056_host_observe.sh): four
  services' image/health/limits, selected source hashes, four allowlisted worker
  environment values, five host/container resource snapshots, and one database
  collector invocation. Anonymous container aliases are stable within the
  window. No command lines, customer payloads, raw logs or full inspect output.

Metadata includes migration ledgers, feature-object presence, schedules,
heartbeat timestamps, capacity templates, bounded active/queued/stalled run
summaries and grouped binding cadences. System samples include connection/wait
groups, blocker counts, database counters and known-table write/vacuum estimates.
No SQL text, user/client/source/run identifiers or scope identity is emitted.
Job keys and policy templates are code-defined metadata, not customer labels.

## Execution sequence after authorization

1. Use the workspace helper with the verified SSH profile. Confirm the approved
   target and helper/tool availability without printing profile values/secrets.
   Do not invoke Portainer. Create a new `/tmp/plan056-task3.XXXXXX` directory
   with `mktemp -d`; retain its exact returned path. Do not reuse another run.
2. Transfer only the two reviewed files to that directory using SCP and the same
   private SSH target. This file transfer is part of the requested temporary-file
   scope; all remote diagnostic commands run through Invoke-DevTool.ps1.
   Compare SHA-256 with local files. Abort on mismatch; do not execute.
3. Confirm `/tmp/plan056_db_observe.py` is absent inside `ninja-operations`.
   Abort rather than overwrite an existing file. Use `docker cp` to copy the
   reviewed database collector there, then verify its hash. Use the current
   runtime role; do not fall back to a migration/superuser role on failure.
4. Through the helper, invoke exactly:

   ```sh
   timeout 180 sh /tmp/<exact-created-directory>/plan056_host_observe.sh
   ```

   Substitute only the verified directory returned by mktemp. Run once. The host
   launches one `timeout 120 docker exec ninja-operations python
   /tmp/plan056_db_observe.py` alongside its five samples. No inline Python.
   Preserve redacted outputs in the evidence record, not a raw customer log.
5. Report failures and permission gaps without rerunning. Both scripts are
   finite; database statements have server-side deadlines. If the host collector
   fails, its already-running database observer may finish its bounded samples;
   do not launch a replacement. Wrapper timeouts alone do not prove a remote
   process ended: verify collector completion using the fixed script identity,
   without dumping other process arguments. No broad kills or SQL cancellations.
6. After confirmed completion, remove only the transferred database file and
   the two exact host files, then remove the now-empty created directory with
   `rmdir`. Verify paths/hashes before removal; no recursive delete or wildcard
   cleanup. If completion is uncertain, report residual artifacts and stop.

The overall task 3 budget remains 10 minutes; observation wrappers are stricter
at 180/120 seconds. No repeated observation windows are authorized by this scope.

## Limits and known gaps

- Metadata/function calls may fail on the runtime role; this is a gap, not a
  reason to escalate. Role visibility flags do not guarantee all sessions are
  visible. SQL has not been executed or parsed by a local PostgreSQL server.
- Host and DB windows have separate UTC timestamps and may be offset by metadata
  work. Compare only overlapping intervals; do not present separate deltas as an
  exact simultaneous breakdown. Counter resets invalidate the affected delta.
- Docker CPU/memory/block-I/O samples use existing Docker telemetry and consume
  some resources. Diskstats include stacked devices: do not sum logical and
  physical device counters. Root filesystem space does not establish free space
  on every database mount.
- Worker environment values are not proof of running Gunicorn arguments; omitted
  overrides and current process topology may remain unknown. Source hashes prove
  selected files only, not a complete deployed commit or database function body.
- This first pass records pg_stat_statements installation but does not query it;
  query-level statistics, full dependency reasons/claims, function-body identity,
  table/TOAST sizes and detailed retention distribution remain targeted follow-up
  candidates. Current run summaries are capped at 50; no total count is implied.
- Runtime sessions, frontend requests and production performance acceptance are
  outside this pass. Task 3 remains open until results and gaps are reviewed.

## Local validation

Python AST parsing, Ruff check/format, Git Bash shell syntax, registry validation
and whitespace checks passed. Only diagnostic files and planning documentation
were added/updated. No runtime tests, source changes, external access or production
execution occurred. Exact runtime compatibility remains unvalidated.
