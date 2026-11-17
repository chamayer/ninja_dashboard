# PLAN-056 — Item 5: representative filter variants

## Scope and authorization

2026-11-10: user selected item 5 of the restored checklist. This executes the
existing full read-only measurement authorization, including normal configured-
admin login/logout and temporary diagnostic transfer/cleanup. No further
permission request is needed for this bounded filter pass. No runtime fix,
new account, synthetic session, business action, export or Coverage request.

## Selected variants and local GET review

| Order | Route, first then immediate repeat | Reason |
| --- | --- | --- |
| 1 | `/devices/?os=Windows` | Supported OS equality filter on the SQL-paginated Computer list. |
| 2 | `/inventory/source-records/?type=agent.rmm` | Supported record-type equality filter before count and page selection; facets remain global. |
| 3 | `/patching/?role=server` | Whitelisted role filter over finding and posture populations. |
| 4 | `/software/?safety=high` | Supported risk-band path that additionally loads the complete safety snapshot before resolving matching titles. |

All values are public category names, with no client, device, product or source
identifiers. Four paired variants, eight measured GETs maximum. Default order,
first page, no CSV/actions. Existing page-two observations are not repeated.
The normal GET handlers were previously reviewed; this local review confirms
the selected parameter branches read populations rather than enqueue work.
Source gates require installed views/context byte hashes from earlier reviewed
HEAD identities before authentication. A hash mismatch stops without HTTP.
HTTP 200 proves response completion, not result correctness or nonempty results.

## Artifacts, limits and execution

`plan056_http_filters.py` sets only the reviewed matrix's fixed route tuple and
its unique temporary stop path, then invokes the existing authentication and
measurement functions. Transfer it with unchanged `plan056_http_matrix.py`,
`plan056_http_pilot.py`, `plan056_db_observe.py` and the existing completion
filter. A filter-specific copy of the reviewed host wrapper supplies passive
15-second samples, a 300-second collector limit and exact stop/done paths.

Reuse the existing runtime-role, tenant-1 SQL snapshots before/after each GET;
3-second statement, 1-second lock and 5-second idle deadlines. Snapshot results
are aggregate counters and at most 20 recent active Jobs; they do not isolate
per-page costs, old active runs or hidden locks. Eight requests, 20 seconds each;
no redirects/assets/browser execution. First/repeat cache state remains unknown.
Stop on first non-200, timeout, SQL failure or observer failure; no retry or
skip ahead. Normal logout is the only subsequent HTTP housekeeping.

Use Windows PowerShell 5.1 and the shared SSH helper on the existing production
profile. Fresh `/tmp/plan056-item5.XXXXXX`, absent container paths, SHA-256
verification before execution. Invoke Python by copied file path, never inline.
Outer host wrapper 360 seconds; total setup/run/completion/cleanup budget
15 minutes. Capture complete redacted output outside Git before summarizing.

Read at most 10,000 log lines from the last 15 minutes using the existing
exact-prefix completion filter. Compare attempted markers 1–8 and HTTP status.
On missing completion after failure, at most 70 seconds observation and one
final completion read; no cancellation, termination or next measured GET.
If work survives, report it and stop. Do not infer server completion from the
client deadline or Gunicorn worker timeout.

After process completion, hash-check/remove only the exact transferred
container and host diagnostics, known stop/done files and empty private host
directory. Verify absence. No recursive/wildcard cleanup or existing-path
overwrite. Local validation is syntax, focused Ruff, shell syntax, registry,
whitespace and blueprint size; no new tests or application performance run.

## Result

Completed once, 2026-11-10, 21:54:44–21:55:38 UTC on the existing production
target. Both installed-source gates passed before normal configured-admin
authentication. All eight requests returned complete HTTP 200 bodies; all
eight exact request markers matched HTTP 200 completion logs. Matrix and
host wrapper exited 0. Logout returned 302 with session-cookie removal confirmed.

| Variant | First complete HTML | Immediate repeat | Body bytes, each |
| --- | ---: | ---: | ---: |
| Computers, Windows | 2.620 s | 1.305 s | 129,997 |
| Source Records, agent.rmm | 5.574 s | 5.392 s | 138,644 |
| Patching, server | 3.734 s | 3.732 s | 117,748 |
| Software, high risk | 18.080 s | 12.589 s | 47,381 |

All requests stayed within their 20-second deadline. There was no timeout,
retry, cancellation or Coverage request. Equal body byte counts within pairs
do not establish content equivalence. Cache/worker state was not controlled;
these are first/repeat observations, not cold/hit measurements. The fixed safety
filter activates a broader safety-snapshot read than default HTML; the timing
alone does not isolate that query or prove the cause of Software's delay.
Concurrent workload differs from earlier baselines; no speedup/regression ratio
or universal latency percentile is claimed.

Whole-database counter differences across the before-1/after-8 snapshots:
1,546,994 blocks read, 2,522,457 buffer hits, 31 temp files/312,595,577 temp
bytes, 6,734 inserts, 474 updates, 6,672 deletes and zero deadlocks. Both reset
timestamps were null, so these are observed differences without a certified
reset epoch. Recent active snapshots included resolver and platform-evaluate.
These global counters include concurrent Jobs; they are not filter-query cost,
physical disk I/O or per-job attribution. Passive host sampling completed.

Six host/four container diagnostic copies matched local SHA-256 values before
execution and cleanup. Exact copies, observer.done and the empty private host
directory were removed; absence and the unused stop-path absence verified.
Complete redacted capture remains outside Git. No response body, credentials,
cookies or customer identifiers were emitted or saved. No runtime/test/schema,
configuration, release, commit or deployment changes occurred.

Collector SHA-256:
`6304963e29efba89a589158b53f792833b3337bed7d2b956891241054845622c`;
host wrapper:
`f42ff3aadd9f842fd3fae9c41e710fa4b6b31df6f44756e8070c0a2fae025e2b`.
Unchanged matrix/authentication/SQL/completion hashes match prior execution
records. AST, focused Ruff check/format, shell syntax, registry, whitespace
and blueprint-size validation pass.

Item 5 is complete for the selected representative filter scope. It is not an
exhaustive filter matrix or population/parity/export certification. Existing
page-two observations remain separate. Next is item 6, browser loading; full
external-network behavior remains item 7. No additional fix is selected here.
