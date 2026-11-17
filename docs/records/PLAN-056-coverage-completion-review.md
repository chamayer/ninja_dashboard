# PLAN-056 — Coverage completion check

Prepared and approved/executed 2026-11-10; see results below. Task 4 remains
incomplete. Before any more
page GETs, distinguish historical completion from current surviving database
work. Existing runtime role visibility could not answer the latter. This is a
new, explicit monitoring scope; earlier runtime-role approval is not reused as
permission to connect through a different database identity.

## Exact scope for approval

One read-only check on am-ch-01: health/start timestamps for Operations/Postgres,
one filtered historical access-log read, and one system-catalog snapshot via the
repository-documented `docker exec ninja-postgres psql -U ninja -d ninja` local
inspection connection. This existing identity may be privileged; the query
reports visibility flags and uses read-only connection/transaction settings.
Do not grant privileges, change roles, disable RLS, expose query text, read
business tables, rerun the page, cancel work, restart anything or mutate data.
Temporary transfer/hash-check/cleanup of these two files is included:

- [Wrapper](../../scripts/diagnostics/plan056_coverage_completion.sh)
- [Catalog SQL](../../scripts/diagnostics/plan056_coverage_completion.sql)

The exact Coverage marker is fixed to the ninth main-pass request. Log interval
is 2026-11-09 22:47–23:02 UTC, capped at 10,000 lines, 10 seconds; output is
only matching completion status/log timestamp or an explicit missing result.
Missing/rotated/truncated logs cannot establish noncompletion. The snapshot
returns visibility flags plus at most 25 Operations sessions' start/state/wait
times, blocker counts and two booleans describing a known Coverage query shape.
It returns no SQL text, users, client/source identifiers or payloads.
Three-second statement, one-second lock and five-second idle limits; 12-second
psql wrapper, no retry/fallback. No session authentication or new HTTP requests.

Prepare a fresh `/tmp/plan056-coverage.XXXXXX` directory via the shared helper;
SCP the two exact reviewed files to the same target, verify SHA-256, then invoke
`timeout 30 sh /tmp/<exact-created-directory>/plan056_coverage_completion.sh`
through Invoke-DevTool.ps1. SQL is piped as data directly to psql; no Python.
Record aggregate results, hash-check/remove only these files, then rmdir the
empty directory. Do not overwrite/reuse another run or recursively delete.
Normal completion should fit within one minute including transfer and cleanup.

## Interpretation

A matching access log can establish the historical HTTP response. Current
session start/wait times can identify surviving candidates, but cannot prove
which HTTP request owns a query because the marker was not propagated to SQL.
Query-shape similarity is a lead, not exact attribution. No active candidate
does not reconstruct the past outcome or rule out non-database work. A service
restart may bound possible survival but is not proof the original request
completed successfully. Any cancellation requires its own exact attribution
and approval; this check does not authorize it.

After results, decide whether six untouched pages can be measured in a separate
bounded continuation, excluding Coverage replay. Preserve ordinary-user/cache
limitations. Task 4 stays open until remaining measurements/gaps are reviewed.

## Validation and handoff

Shell syntax, local static SQL review, registry and whitespace checks pass;
SQL has not run locally or remotely and monitoring-role access is unverified.
No application changes or new production access during this preparation.
Current confirmed state and this next action are in PLAN-056's blueprint.
Executed once after explicit approval: wrapper exit 0, no historical completion
marker, zero current Operations-labeled sessions under full statistics
visibility. Both services healthy; hash-verified temporary files/directory
removed and absence confirmed. Historical outcome remains unknown. See the
[evidence](PLAN-056-platform-performance-assessment.md#task-4--approved-coverage-completion-check-2026-11-10).
Next: prepare a separate six-page continuation without Coverage replay; obtain
approval for that concrete pass before new external observation.
