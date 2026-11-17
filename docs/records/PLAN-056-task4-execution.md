# PLAN-056 — Task 4 request preparation

2026-11-09: pilot executed successfully; see the
[evidence record](PLAN-056-platform-performance-assessment.md#task-4--accesscompletion-pilot-succeeded-2026-11-09).
The main matrix remains unexecuted and task 4 stays open. User identified
credentials in the Docker host .env as the access path. Use mounted credentials
inside Operations without displaying/transferring them. No browser connector or
authenticated Operations HTTP profile is available. Task 3 approval did not
include HTTP requests or authentication/session mutations.

## Access and completion pilot for approval

[HTTP collector](../../scripts/diagnostics/plan056_http_pilot.py) performs one
login-form GET, one normal admin login POST, one marked Settings GET, then one
normal logout POST. Username follows the existing seed convention; password
is loaded in memory from the mounted environment. No user enumeration,
impersonation, password reset, Django test client or synthetic session insertion.
The normal login can update last_login, create a session and generate access
logs; logout deletes that session. These effects are included in the requested
scope, as are ordinary session housekeeping and temporary script transfer/cleanup.
Do not run the password bootstrap management command.

The request goes to internal loopback port 3002 and returns status, header/body
timing, body byte count and a random non-secret marker only. Response contents,
cookies, credentials and raw logs are never returned. No redirects are followed.
Settings requires superuser or manage_catalog permission, so a successful page
also verifies this login's applicable admin access. Label results configured_admin;
no ordinary-user inference is valid. The code expects default session/CSRF cookie
names and internal HTTP support; any mismatch is a reported gap, not a bypass.

Page deadline is enforced by a Unix signal at 20 seconds; authentication and
logout use 20-second network timeouts. Wrap collector execution in 90 seconds.
Timeout/disconnect stops the pilot. The only subsequent HTTP action is normal
logout housekeeping, not another measured page. Do not claim session cleanup
unless logout confirmation is emitted. No credentials/session file is persisted.

[Completion filter](../../scripts/diagnostics/plan056_access_completion.sh) reads
at most 5,000 Operations log lines from the last 120 seconds and emits only the
exact marker and numeric HTTP status. It relies on the existing access-log
format, which must be demonstrated by this pilot. It cannot identify a SQL
backend or cancel a query. If no completion is observed, allow at most 70 seconds
of follow-up observation (one final bounded log read after waiting); make no
further page request. Missing/late logs are a gap, not proof the request ended.
Gunicorn gthread worker timeout is a liveness setting, not a per-request deadline.

After approval: create a fresh `/tmp/plan056-task4.XXXXXX` host directory, SCP only
these two reviewed files using the same private target, verify hashes, and copy
the HTTP script into ninja-operations at `/tmp/plan056_http_pilot.py` only if
absent. Through Invoke-DevTool.ps1, invoke by path:

```sh
timeout 90 docker exec ninja-operations python /tmp/plan056_http_pilot.py
```

Use the emitted marker as the sole argument to the host completion filter via
the helper. After collector completion, hash-check and remove only the exact
copied files; use container root for root-owned temporary-file removal if needed,
never for database access. Remove only the now-empty host directory. Record any
incomplete request/session cleanup; no retries, cancellations or permission grants.
This pilot adds no passive resource window; task 3's sample is not simultaneous.

## GET audit and main measurement matrix

Reviewed selected views, their 65 reachable same-module helpers, shared
middleware/context, client-directory readers, policy loader and domain summary
readers. No business mutation was identified in the selected normal GET paths.
This is scoped static review, not proof against every database-function or
template behavior. No production request was made during review.

| Route | Initial scope | Side effects / interpretation |
| --- | --- | --- |
| `/admin/settings/` | Pilot; later first/repeat | Render plus shared navigation; requires superuser/manage_catalog, not just is_staff |
| `/` | Later first/repeat | Domain summaries; role-dependent cards; deployed version has no uncommitted Home cache |
| `/orgs/all/` | Later first/repeat | Fleet client directory; no client identifier in query |
| `/devices/` | Later first/repeat | Current Computers, default first page |
| `/inventory/computers/` | Later first/repeat | Coverage handler; do not duplicate `/coverage/` |
| `/findings/` | Later first/repeat | Reads remembered view/group state; may save grouping preferences in this new normal session even without a view parameter |
| `/sources/` | Later first/repeat | Source overview; refresh actions are separate POST routes |
| `/inventory/source-records/` | Later first/repeat | Default first page; no export, search, client/source IDs or action parameters |
| `/software/` | Later first/repeat | Overview reader; decisions/actions separate |
| `/patching/` | Later first/repeat | Default queue; no export or action |
| `/admin/jobs/?refresh=off` | Later first/repeat | Disable normal browser refresh; HTTP collector never executes returned JS |
| `/admin/jobs/status/` | Excluded from timing matrix | Legacy redirect to Jobs by default; not another rendered workload |

The later matrix is 11 route variants, at most 22 GETs, sequential, admin session
only. It needs an exact reviewed collector and authorization after the pilot
establishes access/completion. Add overlapping passive observation with bounded,
corrected current-job selection then; do not reuse the oldest-stalled selection
or silently rerun task 3. No ordinary-account credentials are currently identified.
Any ordinary-user phase or filtered/paginated variant needs explicit scope.

Shared work to investigate in task 5: non-Home authenticated renders load the
active client roster, Issues/Patching badges use process-local 60-second caches,
and `/admin/` renders add merge/client/entity candidate counts. These reads can
make even a render-only Settings page expensive. Avoid pre-warming them with
unrecorded page visits. First-observed and repeat are not proven cold/hit states.

## Local validation and gate

Python AST, Ruff and formatting checks; Git Bash shell syntax; registry and
whitespace validation pass. No new test files or application edits. No production
access occurred in this preparation. Exact HTTP/auth/log behavior is unverified.
Pilot completed: 200 in 1.783 s, exact log completion and logout confirmed,
temporary files removed. Next: prepare/review the main request/resource pass.
Task 4 stays unchecked until evidenced
page measurements and their limits are recorded.
