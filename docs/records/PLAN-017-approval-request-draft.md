# PLAN-017 — Diagnostic approval request

2026-10-25. **A/B1 approval is retained from the user's earlier "all approved";
B2 remains separate. C is assigned to Claude in a new session by subsequent
user direction (Point 38), not to the user as a manual browser task.**
That handoff requires minimal commands/output review and confirmation before
production use. No diagnostics have executed. Round 19's statement that its
direction does not approve A/B1/B2 adds no approval and does not revoke the
prior explicit A/B1 approval. No new A/B1 approval request is necessary.

H1 remains applied in the [exact queries/protocol](PLAN-017-diagnostic-queries.md).
The H2 human procedure is superseded for C. Static gate destinations remain
separate; whole-gate acceptance is not inferred.

The following is the scope of the user-facing approval request.
No executable command, credential, production hostname or customer identifier
is included here.

---

May we perform the following diagnostic batches independently? You may approve
any subset of A, B and C; declining C does not block A. The linked exact SQL,
roles, request shapes, limits and stop conditions define the scope.

**A — D1/D2/D5 metadata and aggregate reads.** Codex would execute these through
the approved workspace helper/private profiles as `operations_migrate`, using
read-only transactions, `search_path = pg_catalog`, tenant context 1, a 1-second
lock timeout and 5-second statement timeout. Each batch has a 30-second wall
budget; no automatic retry or cap expansion. D1 returns at most 1,000 metadata
rows per body/10,000 total. D2 takes two separately scheduled statistics/size
snapshots, 15–60 minutes apart; the 30-second limit applies to each capture.
D5 uses at most 5,000 sampled keys per sampled dataset, **except D5.2**:
that is an uncapped aggregate over all tenant-1/source receipts within 30 days,
broken down only by `split_part(kind, '.', 2)` (platform). No full kind or
customer-bearing source_key is returned. The 5-second statement timeout bounds
execution; timeout produces no complete counts. D5.3 selects pending targets
directly. Both require an affordable plain plan using their installed indexes
before SELECT execution; otherwise skip and report the gap. Limits on returned
rows do not bound all scanned work. Role/grant/index mismatches stop dependent
checks; no role substitution, grants or schema changes are permitted.

This is a privileged role declared BYPASSRLS in local migrations, although these
queries return only schema metadata, statistics and aggregates. It is not a
runtime-role tenant-isolation test. Results establish measured observations at
capture time, not a production-wide integrity or history guarantee.

**B — D3 privileged integrity checks in two stages.** B1 authorizes plain
`EXPLAIN (ANALYZE FALSE)` only for the exact D3 SELECTs, as
`operations_migrate`, under A's read-only wrapper/time limits. D1 reconciliation
must precede dependent queries. We would report the plans and access/cost gaps
before B2, quoting each statement's **actual B1 startup/total plan cost and
estimated row count**, plus relevant expensive-node estimates/access paths.
These are planner units/estimates, not measured milliseconds; none is available
yet and none will be invented. **B2 SELECT execution requires a separate explicit go-ahead after
that plan review**; B1 alone authorizes no D3 data query execution. B2 retains
the 5,000-key sample caps, 5-second statement/30-second batch budgets and
aggregate-only output. D3.6 directly queries tenant-1 queued/running Jobs using
their active-state index; a saturated sample is a lower bound. Privileged
results cannot establish what `operations_app` can see.

**C — Claude-run runtime SQL and metrics-only HTTP, new session.**
Claude owns D4 P0, plain plans, aggregate/EXPLAIN ANALYZE SQL as operations_app
and the 15 HTTP shapes, using minimal reviewed commands. Retain the separate
operations,public read-only wrapper, tenant context 1, 1-second lock/15-second
SQL statement and 30-second sub-batch bounds. SQL ANALYZE executes queries and
adds load. No client-filter bindings/probes are reintroduced.

Point 38 requires Claude to verify the helper's operations_app database path
and authenticated HTTP path privately, show the minimal commands/output
contracts and obtain confirmation before production execution. Missing paths
stop C; no privileged substitution, alternative session creation or widened
scope. Do not assign manual browser measurements or CSV downloads to the user.
The historical H2 human procedure is superseded for this execution method.

Every command must output metrics only: public route shape, status, bytes,
timings, reviewed numeric counts/completion/parity flags and SQL plan cost/time
numbers. Never expose customer identifiers, full source kinds, response bodies,
CSV records, auth/session headers, private URLs or raw errors. Stream a proper
CSV parser for complete data-record counts (quoted newlines matter); null sinks
alone establish only transfer metrics. No general executor is requested.

Limits revised 2026-10-25 after the first run (see the exact queries/protocol):
15 shapes, at most 25 sequential measured requests including repetitions and
one re-measurement per breached shape, 20-minute total budget, HTML 90 seconds/
8 MiB and CSV 120 seconds/32 MiB/50,000 complete-record limits. Computers CSV
last: population <=50,000, SQL checks passed, no unresolved breach and its full
deadline remaining; the former all-HTML <5,000 ms condition is removed.
Client cancellation does not prove server completion: stop on breach and
re-measure only after the server is confirmed to have finished. Suppress
sensitive output/files and clean up any unavoidable private temporary data.

CLI results are not browser render/DevTools results; record the actual method,
cache conditions and missing-metric gaps. Normal session/access bookkeeping
may occur during requests; C is application load, not zero-write assurance.
Save allowlisted results only to docs/records/PLAN-017-d4-results.md.

All batches stop for timeout, missing/denied objects, unreviewed definitions or
unsafe/unaffordable plans. No retries, parameter expansion, source API calls,
maintenance, data repair, migrations, refresh/rebuild, deployment, runtime
configuration changes, commit or push are included. These approvals would cover
only the diagnostic work stated above, not Phase 2 experiments or later design
implementation. Later-phase effort remains an estimated 7–16 engineer-days plus
required Phase 1 amendments and access/setup delays, subject to reviewed scope.

A/B1 are already approved within the exact limits above. C belongs to the
new Claude session with the command-review/confirmation boundary at Point 38.
B2 will be requested separately quoting actual B1 plan costs and row estimates.
No B2 approval is inferred from either earlier "all approved" or the C handoff.
