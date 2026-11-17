# PLAN-056 — Controlled cold navigation: method review

## Status and scope

Prepared 2026-11-10 on resumption of PLAN-056; subsequently deferred by the
user until post-fix verification. No method selection or approval is pending.
No external command, authentication, page request or additional application
server was started. The proposal below is retained for reference only.

## Confirmed local findings

- `context_processors.py` caches the tenant's Issues and Patching navigation
  counts for 60 seconds. Home supplies its own Issues count and skips the
  Client roster; Settings also reads the roster and admin candidate counts.
- Current settings declare no custom cache backend. The earlier deployed
  diagnostic confirmed LocMemCache in its own process; this is historical
  evidence, not a fresh inspection of the running workers.
- Existing HTTP collectors record status, header/body timing, bytes and exact
  completion markers. They cannot observe the serving worker's cache state.
- The earlier cold/warm context measurement used a fresh diagnostic process,
  a synthetic request and no HTTP, session loading or template rendering.
  It cannot satisfy the full-page cold requirement.
- Gunicorn access logs record completed requests. A quiet log interval does
  not rule out an in-flight request that could populate a cache. Login alone,
  a 60-second delay or another first/repeat pair would not prove a cold miss.
- Uncommitted Home caches and middleware timing remain preserved. They must
  not be substituted for installed behavior in this measurement.

## Proposed bounded method

Start one additional, temporary Gunicorn master with one fresh gthread worker
inside the existing Operations container, using installed code, production
settings and the existing runtime database role. Bind only an unused container
loopback port; preserve the normal Host header. Do not invoke the entrypoint,
migrate, reload/restart the live service or expose another host port.

The collector would own the temporary process and its children, admit only its
own sequential HTTP requests, and retain credentials/cookies in memory using
the reviewed normal configured-admin authentication helper. Do not follow the
login redirect or fetch assets. Confirm the installed login path does not
populate authenticated navigation caches before admitting the measurement.

Measure Home only: one first authenticated GET of `/`, then one immediate
repeat only after a complete HTTP 200. Maximum two measured GETs, each with
a 20-second client deadline; normal login/logout housekeeping is included.
Record UTC, endpoint, status, header/full-body times, byte counts and exact
completion markers; discard HTML. No Coverage page, Jobs or business action.

Use a 120-second total collector bound, including at most 70 seconds of
completion observation after failure. Stop on the first error; no repeat after
failure. Attempt normal logout, then stop only the collector-owned temporary
server and verify its children/listener have exited. Terminating this server
after an incomplete request is a production diagnostic-process change and
must be included in approval; it cannot be treated as passive observation.
Do not cancel or terminate any existing service, worker, backend or Job.

Before execution, prepare and review the exact collector, process-ownership
checks, source/cache gates, deadlines and cleanup. Use the shared helper,
fresh absent temporary paths, SHA-256 verification and exact-file cleanup.
Run syntax/lint checks only; no new tests, dependencies or runtime-file edits.

## Interpretation and decision gate

This would measure real HTTP through a fresh installed application worker,
including authentication/session loading, middleware, view, context and
templates. It establishes cold application navigation state only after the
gates above pass. Database/OS buffers remain uncontrolled. A single isolated
worker is not the live three-worker pool, browser rendering or external
networking; its repeat is useful as a same-worker observation, not a load test.
Startup time is outside request timing. Admin results remain admin-only.

User decision: defer controlled-cold verification until after an approved fix.
The fresh-worker proposal is withdrawn from current execution. Resume the
remaining platform assessment; no instrumentation release is a prerequisite
to that assessment. Cold-response acceptance remains open for post-fix
verification, with its measurement method to be reviewed then.
