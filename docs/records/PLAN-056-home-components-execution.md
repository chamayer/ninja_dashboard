# PLAN-056 — Home summary component attribution

Prepared 2026-11-10 to attribute the confirmed slow Home request before
selecting a remedy. The deployed configured-admin requests took 8.983 s and
6.828 s; the accepted target remains ≤1.5 s ordinary and <2 s hard, including
cold navigation. This diagnostic measures Home's data-reader functions only,
not HTTP latency or cold-cache acceptance.

## Exact scope for approval

One pass on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations, using the
existing runtime database role. One read-only repeatable-read transaction,
tenant 1, 3-second per-statement deadline, 1-second lock deadline and 5-second
idle-transaction deadline. Run each of these ten Home data readers once, in
Home order: device-status policy; Clients; Computers; source inventory; Issues
summary/attention; Patching; Coverage; Software; Sources; Jobs. Stop on the
first query or component error. No retry, alternate role, SQL instrumentation,
HTTP/auth/session, template rendering, shared navigation/context processors,
Jobs execution, cache flush, query cancellation, grants, app/schema/config/data
change, or candidate fix.

The probe calls the deployed reader functions directly, not the view. It
measures elapsed time per reader, discards return values in memory, and emits
only UTC, its own backend PID, component label, elapsed time, error class/SQLSTATE
and connection-closure marker. It emits no counts, summaries, names, IDs, SQL,
parameters, credentials or error messages. It does not attribute shared Client
navigation, Issues/Patching badges, staff-only admin counts, middleware,
template work, or network/render time. A repeatable snapshot improves
within-pass consistency but may differ from the request's isolation/cache state.

Before connecting, the collector checks SHA-256 of all ten source modules
against HEAD `ca00938a`; any mismatch stops without a database connection. The
readers are called once in the exact Home order. Each SQL statement is bounded
by the server deadline. An error ends the transaction and the probe; no
component after the first failure runs. The outer process is limited to 60
seconds, with kill after 5 seconds.

Temporary files within this scope:

- [Collector](../../scripts/diagnostics/plan056_home_components.py), SHA-256
  `278cf1660413b0545d58470e6b5fb67dcddd7bdd69bee5b337a8654a5f34b05d`.
- [Unchanged output helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private host directory
`/tmp/plan056-home-components.XXXXXX`. Verify both hashes and ensure exact
Operations destinations `/tmp/plan056_home_components.py` and
`/tmp/plan056_coverage_components.py` are absent; confirm
`/usr/bin/timeout` is executable. Copy only these files and verify hashes.
Invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_home_components.py
```

Five-minute setup/execution/cleanup budget. Preserve sanitized aggregates.
Hash-check and remove only these exact host/container files, remove the empty
host directory and confirm absence. Stop on source mismatch, query timeout or
any error; no retry. A timeout is incomplete evidence. If the connection-close
marker is missing without confirmed process termination, leave execution
unresolved and do not cancel other work.

## Preparation checks and gate

Local SHA-256 values were derived from `git show HEAD:<module>` for the ten
gated source files. Python AST syntax parsing passed. No external access,
application/test changes or runtime calls were performed. Live source hashes,
query behavior and timings remained unverified at preparation time. The
approval gate was subsequently satisfied; the single invocation outcome
follows.

## Approved invocation outcome — 2026-11-10

After explicit approval, one invocation ran on verified host `am-ch-01` through
the shared helper. Both deployed transfer copies matched the reviewed SHA-256
before execution and after completion. The ten source-module hash gates passed.
One repeatable-read, read-only tenant-1 transaction ran with own backend PID
358011:

| Component | Result |
| --- | --- |
| Device-status policy | Completed, 0.027 s |
| Clients | Completed, 0.016 s |
| Computers | Completed, 0.271 s |
| Source inventory | Completed, 1.716 s |
| Issues summary/attention | QueryCanceled/57014 at the 3-second statement deadline; observed component elapsed 3.019 s |
| Patching, Coverage, Software, Sources, Jobs | Not attempted under stop-on-first-error |

`measurement_finished` reported status 1 and connection closure. The probe
stopped at the Issues failure; no retry, HTTP, authentication/session, job,
other backend cancellation, result-value output or business/configuration
change occurred. All result values were discarded. Exact host/container files
matched hashes before removal; both files and the empty host directory were
removed and absence confirmed. Container root was used only for exact temporary
file cleanup.

This attributes a statement deadline to the Home Issues reader and records a
completed source-inventory component pass. It does not identify an internal SQL
node or explain the full Home response. The `source_inventory` component's
1.716 seconds includes its reader work in this single run; it is not a general
HTTP cost or comparable-load benchmark. Shared navigation/context, rendering,
and later summary components remain unmeasured. Task 5 is still partial; no
fix was authorized.
