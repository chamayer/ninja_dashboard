# PLAN-056 — Client and Computer detail diagnostics

On 2026-11-19, configured-admin internal HTTP to a client overview exceeded the
20-second limit; server completion was not observed in two bounded log checks.
Separate read-only direct-handler traces on release 0.144.41 found the client
mapping count took 6.481 s and an unused active-finding count hit 10 s. The
Computer's per-title installation-evidence query hit 10 s. Traces stopped at
the database deadline, so those are not complete page timings.

Within one read-only snapshot the mapping count matched with JIT on and off:
6.089 s and 0.140 s. A corrected compact count and an early client predicate
also matched in individual comparisons but produced only marginal gains.

For the Computer, the existing domain evidence view was batched over selected
software titles. In one snapshot a 10-title slice matched the old query:
1.139 s versus 9.288 s. The candidate for up to 300 titles ran in 1.165 s,
while the old query hit a 12-second deadline; full result parity was not shown.

An isolated client-handler diagnostic bypassed unused counts/rollups and scoped
JIT off for the mapping count. It returned 200 in 4.481 s, including a legacy
severity query taking 1.483 s; the current local candidate removes that query.
The current issue rollup took 1.268 s. A separate Computer-handler diagnostic
bypassed evidence on Overview and returned 200 in 6.757 s. Its remaining
software display-name query took 3.384 s; the local candidate skips title label
and decision work outside the Software tab. These were instrumented handlers,
not browser or deployed-candidate timings. Row contents were not emitted; normal
connection closure and exact temporary-file cleanup were confirmed.

One client-scoped issue-rollup comparison returned identical grouped rows using
the existing correlated ownership predicate: 0.037 s versus 0.734 s for the
original global-ID subquery. The local candidate changes only the client scope;
fleet directory ownership behavior stays as before. This is one snapshot, not
general parity or a sustained performance claim.

An isolated read-only process loaded the exact local candidate files without
changing serving code. Client overview returned 200 in 1.800 s, Computer
Overview 200 in 3.535 s. A corrected routing invocation returned 200 at 1.567 s,
2.860 s and 7.613 s for Client, Computer Overview and Computer Software.
The Software tab spent 3.643 s resolving preferred software names; batched
evidence took 0.974 s. These are isolated handler timings, not full HTTP/browser
measurements or full output-parity proof. Connection closure and exact staging
cleanup confirmed. User requested testing stop; no further tests or diagnostics.

Local changes in `operations/apps/core/views.py` and `client_workspace.py` are
not tested or deployed.
Review output parity, JIT setting restoration, tenant scope, full evidence
equivalence and production page timing before treating the work as complete.
No local tests were run, per user instruction. No new schema is proposed.
