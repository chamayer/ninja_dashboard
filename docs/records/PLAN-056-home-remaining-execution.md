# PLAN-056 — Remaining Home reader attribution

Prepared 2026-11-10 after the approved Home reader pass stopped at the Issues
statement timeout. This is a separate scope; the earlier approval did not
authorize a continuation or retry.

## Exact scope for approval

One pass on am-ch-01 through `Invoke-DevTool.ps1`, inside Operations, using the
existing runtime database role. One tenant-1 read-only repeatable-read
transaction, 3-second per-statement deadline, 1-second lock deadline and
5-second idle-transaction deadline. The collector calls the device-status
policy once as Patching's input, then calls the five remaining Home readers once
in Home order: Patching, Coverage, Software, Sources and Jobs. Stop on the
first error. No retry, repeat of Clients/Computers/source inventory/Issues,
HTTP/auth/session, template/shared-context processors, Jobs execution,
instrumentation, cache flush, query cancellation, alternate role, grant,
schema/config/data/app change or candidate fix.

The calls are direct data-reader invocations, not the Home view. Return values
are discarded in memory. Output is limited to UTC, own backend PID, component,
elapsed time, error class/SQLSTATE and connection closure. No counts, summaries,
names, IDs, SQL, parameters, credentials or error messages are emitted. The
probe does not measure badges, navigation Client roster, middleware, staff-only
admin counts, rendering, network time or cold-cache acceptance. This separate
snapshot must not be added to earlier timings as an exact HTTP breakdown.

Before connecting, SHA-256 gates compare the ten source modules used by the
Home reader stack with HEAD `ca00938a`; any mismatch stops before database
access. Each SQL statement is server-bounded. The outer process is limited to
60 seconds, then killed after five more seconds. Stop on timeout/error, no
retry. Missing closure without confirmed process termination leaves execution
unresolved; do not cancel other work.

Reviewed artifacts:

- [Collector](../../scripts/diagnostics/plan056_home_remaining.py), SHA-256
  `02486e4c32262561c2d7feb964d1f762357d8cd40c1556739d27836050fc023d`.
- [Unchanged output helper](../../scripts/diagnostics/plan056_coverage_components.py),
  SHA-256 `39a97e8815ab7cbb68f39ed1749fc742e6192e9b5db0bb74fe248bf4633524a6`.

After approval, create a fresh private host directory
`/tmp/plan056-home-remaining.XXXXXX`; verify both hashes, ensure exact
Operations destinations `/tmp/plan056_home_remaining.py` and
`/tmp/plan056_coverage_components.py` are absent, and confirm
`/usr/bin/timeout` is executable. Transfer only those files, verify host and
container hashes, then invoke once:

```sh
timeout 90 docker exec ninja-operations /usr/bin/timeout -k 5 60 python /tmp/plan056_home_remaining.py
```

Five-minute setup/execution/cleanup budget. After completion/failure, hash-check
and remove only the exact files, remove the empty host directory, and confirm
absence. Container root may remove only root-owned diagnostic copies.

## Preparation checks and gate

Local source hashes are derived from HEAD `ca00938a`. No runtime call or
external access occurred during preparation. Live code compatibility remains
unverified at preparation time. The approval gate was subsequently satisfied;
the single invocation outcome follows.

## Approved invocation outcome — 2026-11-10

After approval, one invocation ran through the shared helper on verified
`am-ch-01`. The ten module hash gates passed; own backend PID 358860. The
device-policy dependency completed in 0.025 s. The Patching Home reader then
hit the 3-second statement deadline at 3.009 s (`QueryCanceled/57014`). Coverage,
Software, Sources and Jobs were not attempted. `measurement_finished` reported
status 1 and connection closure. No retry, HTTP, session, Jobs execution,
other-backend cancellation or application/data/configuration change occurred.

Both host/container files matched reviewed hashes before execution and after
completion. Exact files and the empty host directory were removed and absence
confirmed; container root was used only for exact temporary-file cleanup. This
attributes a statement deadline to the Patching Home reader, not a particular
SQL node or the full Home response. No fix authorized.
