# PLAN-017 — A/B1 authorized retry results

2026-10-25. **Part A's bounded diagnostic query set is complete, including
D5.2/D5.3. B1 and subsequently approved B2 are also complete. Phase 1 remains
open.** The initial failed attempts, temporary holds and later approvals are
preserved below as evidence of the execution boundaries. The latest completion
section supersedes earlier pending/skip descriptions; no query remains skipped
for lack of required index metadata. Global catalog/index/constraint coverage
remains limited by the approved row caps.

## Scope, scheduling and preflight

The retry resumed the A/B1 window under the user's latest confirmation that
Claude C was paused. No C SQL/HTTP or manual user measurements were performed.
The unchanged documented helper was invoked through Windows PowerShell 5.1.
SQL/code was encoded for stdin transport; only reviewed A/B1 bodies were sent.
Each numbered body used its own read-only transaction and fresh connection,
with P0 asserted before submitting that body. Actual P0: operations_migrate,
server_version_num 160014, read-only on, tenant 1, pg_catalog; superuser and
BYPASSRLS both true. No runtime-role visibility guarantee follows.

All captured batches were sequential and below their 30-second client wall
budgets: D1 8.016 seconds, D2 first capture 4.265 seconds, B1 4.203 seconds,
D5 6.813 seconds. Each retained the 1-second lock, 5-second statement and
10-second idle-transaction limits. At the initial B1 stage no D3 SELECT ran. The subsequent B2 execution below
was explicitly approved; no EXPLAIN ANALYZE ran.

Before retry, HEAD 70e64f5, all 951 source paths in snapshot-plus-delta and the
original six evidence hashes matched. Existing dirty/untracked work was
preserved. No maintenance, migration, repair, deployment, commit or push ran.

## D1 reconciliation and bounded coverage

D1 returned 3,063 metadata rows, below 10,000 total. D1.1 found all 30
non-Django-alternative expected objects accessible; operations.django_migrations
was accessible and public.django_migrations was absent. D1.9b was skipped as
documented. Operations ledger: 330 rows, lexically last name
0344_source_record_layout_and_url. Ingest ledger: 116 rows, lexically last
version 116_active_installation_lookup_indexes. These observations do not
identify the running application VERSION or establish full migration parity.

D1.2 returned 409 relation metadata rows; D3/D5 inputs are base relations,
not unreviewed view expansions. D1.3 indexes and D1.4 constraints each hit the
1,000-row limit. Index coverage stops at operations.os_instances; constraint
coverage stops at operations.job_schedule_events. Both are incomplete censuses.
No continuation, higher limit or extra catalog query was sent. D1.5/6/7/8
returned 116/265/198/11 metadata rows; D1.11 returned 30 safe-view columns.
Definitions/digests and direct dependency edges do not prove function parity,
full transitive dependencies, RLS correctness or global constraint coverage.

The required run_log and pending software-target indexes lay beyond the
initial capped boundary. Initial D5.2/D5.3 skips were superseded by the user's
explicit direction to finish them. A reviewed targeted D1.3 continuation added
only an operations/two-relation filter, retaining the original SELECT/joins and
1,000-row cap. It returned six index metadata rows: both required indexes are
installed, valid and ready, including their expected definitions. D1 total is
now 3,069 rows; combined D1 client probe time is 10.501 seconds. Global index
and constraint censuses remain capped/incomplete; no cap was expanded.

The subsequent exact D5.2/D5.3 plain-plan attempt returned helper exit 255 after
21.860 client seconds, with no validated plan output. Remote plan submission/
completion is unknown; no SELECT was submitted in that plan-only attempt.
The batch stopped without automatic retry. Combined D5 active client time is
28.673 seconds. Index eligibility is now confirmed, but plan affordability is
not. The two aggregates remain unfinished because of this transport stop,
not because the earlier metadata gap was left unresolved. A fresh-attempt
request is pending under the stop/no-automatic-retry protocol.
D5.2 retains the exact uncapped 30-day platform-only shape; no full kind or
source_key was returned and no shorter window was substituted.

## B1 actual plain-plan evidence

Costs are PostgreSQL planner units, not milliseconds. Estimated rows below
are root output rows, not rows examined or sample population. Full sanitized
node trees are retained in [B1 evidence](PLAN-017-gate-evidence/retry-b1.json).
Expression strings, row values and raw errors are not retained.

| Query | Actual startup cost | Actual total cost | Estimated root rows |
| --- | --- | --- | --- |
| D3.1 | 101663.03 | 101663.04 | 1 |
| D3.2 | 19115.84 | 19115.85 | 1 |
| D3.3 | 5249.36 | 5249.37 | 1 |
| D3.4 | 12843.86 | 12843.87 | 1 |
| D3.5 | 830.07 | 830.08 | 1 |
| D3.6 | 10.67 | 10.72 | 2 |
| D3.7 | 288.90 | 288.91 | 1 |

Material access-path risks:

- D3.1 is the highest-cost candidate. Its 5,000-row primary-key prefix costs
  0.42–16,618.33; two correlated history count subplans each cost 8.44–8.45
  per invocation using uq_obs_hist_open_stable_identity. Repeated lookups can
  multiply work across the sample; root total cost is 101,663.04. Hold B2 for
  this query until the cost risk is explicitly reviewed.
- D3.2 also pays the 16,618.33 prefix cost and hash-joins to a devices sequential
  scan estimated at 6,099 rows (0–2,085.99), plus smaller reference tables.
- D3.3 reads a 5,000-row installation prefix (0.55–2,111.42), but builds hashes
  from whole catalog scans estimated at 51,628 software versions, 24,847 products
  and 5,083 publishers. The sample cap does not cap those scans.
- D3.4's 5,000 daily-presence keys join against an index-only scan estimated at
  92,170 current observations (0.42–10,833.22), plus 5,819 snapshot receipts.
  Index-only access is not proof of zero heap reads; B1 contains no buffer or
  execution evidence.
- D3.5 scans and sorts an estimated 5,819 receipts before taking 5,000. Its sort
  starts at 580.07, and the capped input reaches cost 592.57. The cap does not
  prevent the preceding scan/sort.
- D3.6 is estimated cheaply, but uses idx_operator_job_runs_status
  (0.41–10.60; one estimated matching Job), then a small sort. The dirty input
  uses a sequential scan/sort, each estimated at one row. The draft's expected
  uq_operator_job_runs_active index is obsolete: local migration 0223 explicitly
  drops it, corroborating its absence from the complete operator_job_runs portion
  of D1.3. No missing-index repair is proposed. Hold D3.6 B2 until its stated
  access-path prerequisite is reviewed against the installed path; do not
  silently treat the old partial-index assertion as satisfied.
- D3.7 sequentially scans drift records, sorts an estimated 597 open matches
  (266.52–268.01), then aggregates. A 5,000 cap does not bound the full scan.

B1 completed planning only. It proves neither affordability within five seconds
nor candidate counts, integrity, oldest-global queue age or population-wide
coverage. Index-prefix samples are not random. D3 runs privileged and cannot
establish operations_app visibility or tenant isolation.

## A aggregates and statistics

D5.1 sampled 5,000 history keys: 266 open; 3,174 closed over 30 days; two closed
over 90 days; zero closed over 365 days. The age bins overlap and the prefix
is not a retention/population distribution. No horizon is adopted.
D5.4 found 558 sampled machine capability episodes (542 current, 16 closed)
and zero operator capability episodes in that statement snapshot. No authored
state outside this relation or other scopes was inspected or inferred.
D5.5 returned 68 existing-column statistic rows, excluding histograms and most
common values. D5.2 and D5.3 SELECTs were not submitted for the reasons above.

First D2 capture: 2026-10-25 22:48:41–22:48:43 UTC. Second capture completed
at 23:04:28–23:04:30 UTC; minimum separation across captured rows was
945.169 seconds (15 minutes 45 seconds). Each returned 328 relation rows and
1,000 index-usage rows. Index coverage is incomplete in both. The second
capture used exactly the same D2 bodies, wrapper and P0; client wall time was
6.000 seconds. [Comparison evidence](PLAN-017-gate-evidence/retry-d2-comparison.json)
records matched allocation observations for all 328 relations.

The interval includes ordinary workload and sequential B1/D5 diagnostic reads;
changes cannot be attributed wholly to ingest or any one dataset. Database
stats_reset is null in both snapshots: observed counter differences are
conditional and not proven reset-free. Cluster WAL reset time is the same
known value in both, with 549,058,531 additional WAL bytes across the cluster;
this is not dataset/database-attributable growth. Per-table reset epochs were
not measured. Total allocation increased by 2,752,512 bytes for
operations.entity_candidate_events, 1,777,664 for device_session_current and
1,515,520 for findings_change_history. These are allocation changes, not
logical-data growth, exact churn, bloat or long-term capacity rates.

Individual relation totals include indexes/TOAST and must not be added to
those components again. Largest first-capture totals include device_snapshots
15,170,043,904 bytes, platform_observations 8,187,150,336 bytes and
entity_observation_current 3,005,333,504 bytes. Sizes/row estimates do not prove
exact populations, redundancy or retirement safety.

## B2 explicit approval and aggregate results

The user asked why two queries were held, received the risk explanation, and
then stated "i approve all testing". Within this active diagnostic review this
approved all seven exact D3 SELECTs, retaining the original wrappers/caps/stop
conditions, without authorizing C, later phases or runtime changes. No hold
remains on those seven queries. D3.6's discrepancy was reviewed against D1's
valid/ready idx_operator_job_runs_status definition and local migration 0223's
explicit drop of the obsolete partial index. The installed current path supports
the exact tenant/status lookup; the SELECT and planner settings were unchanged.
See [approval/path review](PLAN-017-gate-evidence/b2-approval-and-path-review.json).

All seven SELECTs completed successfully in 12.063 client wall seconds as one
sequential B2 batch. Every connection passed P0 and every statement retained
the five-second cap; no timeout or retry occurred. Per-query wall measurements
include psql/P0/transaction/transport work and are not isolated server SQL times.
No EXPLAIN ANALYZE or raw rows were returned.

| Query | Safe aggregate result |
| --- | --- |
| D3.1 | 5,000 sampled; one tenant; zero parity or multiple-open candidates |
| D3.2 | 5,000 sampled; 10 client-attribution candidates; all other queried missing-reference/tenant/source mismatch counts zero |
| D3.3 | 5,000 sampled; zero unlinked or missing catalog-reference candidates |
| D3.4 | 5,000 sampled; all queried current/run/scope/provenance candidate counts zero |
| D3.5 | 5,000 sampled; 2,355 complete-count candidates; zero time-order candidates or recorded complete-empty rows |
| D3.6 | Zero active queued/running Jobs and zero effective-dirty rows at the statement snapshot; zero expired-lease candidates |
| D3.7 | 597 open recorded drift rows, all recorded within 24 hours |

The 10 attribution candidates and 2,355 receipt-accounting candidates require
assessment of mapping/accounting semantics; they are not proven contamination
or acquisition failures. The 597 drift rows are existing records, not a fresh
verdict recomputation. Prefix samples cannot prove global integrity; empty
queue snapshots do not establish continuous health. No row IDs/customer data
were retrieved, no fixes were attempted, and no broader follow-up data query
is inferred from these results. [B2 evidence](PLAN-017-gate-evidence/retry-b2.json).

## Remaining gates and concurrent-source handoff

B2 is complete under explicit approval. A still requires D5.2/D5.3 after the
stopped SSH plain-plan attempt; one fresh attempt has been requested, not
silently retried. Reviewed continuation SQL/metadata and the failure record
are retained. C, U02/U04, static coverage review, whole Phase 1 gate and later
phases remain separate and open. No diagnostic completion closes Phase 1.

During the D2 interval, three pinned reader/template/test paths changed and
local migration 0345_restricted_source_layouts.py appeared. HEAD and original
six evidence hashes remained unchanged. The diagnostic file byte digest also
changed, but all captured A/B1 bodies and D2 wrapper/P0 were verified unchanged
before capture 2. No cause is inferred for the file byte change. The
[closing source delta](PLAN-017-gate-evidence/retry-closing-source-delta.json)
preserves the new hashes without overwriting either baseline. Claude's C owner
must reconcile current reader/source/migration expectations before its own
reviewed commands; no deployment/migration state or C execution is inferred.

Evidence: [preflight](PLAN-017-gate-evidence/retry-ab1-preflight.json),
[D1](PLAN-017-gate-evidence/retry-d1.json),
[first D2](PLAN-017-gate-evidence/retry-d2-capture1.json),
[D5](PLAN-017-gate-evidence/retry-d5.json).
The scoped local transport is `.work/plan017_ab1_probe.py`; it is a temporary
diagnostic tool, not an application/deployment change. No production files are
written by its remote process. Raw errors and private configuration are not
stored in evidence.

Additional evidence: [second D2](PLAN-017-gate-evidence/retry-d2-capture2.json),
[targeted index continuation](PLAN-017-gate-evidence/retry-d1-index-continuation.json),
[continuation review](PLAN-017-gate-evidence/d1-index-continuation-review.json),
[remaining D5 plan transport stop](PLAN-017-gate-evidence/retry-d5-remaining-plan.json).

## Subsequent authorized fresh D5 attempt

The user authorized one fresh D5 attempt after the SSH stop. Both exact plain
plans completed in 4.203 client seconds. D5.2 root cost is 318.99–319.02 with
10 estimated platform result rows; it chooses a sequential scan with 1,329
estimated matching receipts. The latest D2 metadata estimates 6,292 run_log
rows and 892,928 main bytes. This small scan may be affordable but does not
meet the written index-backed-access gate. No planner settings were forced.
D5.3 root cost is 40.64–40.65, one output row; its pending index-only input is
0.14–35.44 with 189 estimated matches and passes the documented plan gate.

The 30-second combined fresh window elapsed during client-side plan review
before either SELECT was submitted. This is an executor delay, not a SQL
statement timeout or evidence of an expensive execution. The batch stopped;
no budget was silently reset. A request is pending for one new 30-second
SELECT batch for both, explicitly allowing D5.2's observed sequential scan
for this batch only. Exact SQL, wrapper, five-second statement limits,
platform-only uncapped D5.2 output and other stop conditions remain unchanged.
[Fresh plans](PLAN-017-gate-evidence/retry-d5-fresh-plan.json),
[review](PLAN-017-gate-evidence/d5-fresh-plan-review.json),
[stop record](PLAN-017-gate-evidence/d5-fresh-attempt-stop.json).

## Final Part A completion

After the concrete pending request described the two remaining SELECTs and
the D5.2 small sequential-scan exception, the user directed "finish part A".
This was treated as authorization of that pending one-batch exception and new
30-second SELECT batch. No other protocol exception or scope expansion was
inferred. The exact SELECT and wrapper hashes matched the captured plans; both
required indexes had already been confirmed installed, valid and ready.
No planner settings or runtime configuration were changed.

Both SELECTs passed in **3.750 client wall seconds**, sequentially as
operations_migrate, with P0 on each fresh connection, the unchanged read-only
wrapper and five-second statement timeout. D5.2 completed the exact uncapped
30-day tenant/source aggregate grouped only by split_part(kind, '.', 2):

| Platform | Receipts in 30 days | Successful zero-row receipts | Failed receipts |
| --- | --- | --- | --- |
| Hudu | 124 | 0 | 0 |
| LogMeIn | 132 | 0 | 0 |
| Ninja | 414 | 0 | 39 |
| R-U-ON | 72 | 0 | 0 |
| ScreenConnect | 131 | 0 | 0 |
| SentinelOne | 127 | 0 | 0 |

There were 1,000 matching receipts in total. This observed total is not a
LIMIT: the exact body contains no input/output LIMIT, prefix sampling or
shortened time window. Only platform and aggregate counts/timestamps were
returned; no full kind/source_key, customer identifiers or payloads were
retrieved. The 39 failed receipts were all in the Ninja platform aggregate;
this does not establish their failure cause or a current service incident.
D5.3 returned zero sampled/pending software targets and null oldest/newest
pending timestamps at that statement snapshot. It retained the 5,000-key cap;
zero pending at one snapshot does not establish continuous queue health.

All applicable numbered D1/D2/D5 bodies are now captured. D1.9b was inapplicable
because the alternative public Django ledger did not exist; the accessible
operations ledger was queried. D1/D2 capped metadata is still incomplete
census coverage, and the two D2 snapshots do not establish long-term capacity
or reset-free database/table-counter rates. No diagnostic result closes the
whole Phase 1 gate, U02/U04, static coverage, C reconciliation or later phases.

The Codex A/B probe window is released; no Codex probe remains active.
Claude's separately written C checkpoint reports C work and no active C probe;
actual scheduling overlap and deployment consistency were not verified here.
The latest local HEAD is fcb488a from concurrent work. This session created
no commit/push/deployment, and local Git state is not evidence of production
version. Preserve Claude's checkpoint and results without attributing its
production actions to this execution or inferring its approvals from ours.

Final evidence: [SELECT aggregates](PLAN-017-gate-evidence/retry-d5-final-select.json),
[authorization/one-batch exception](PLAN-017-gate-evidence/d5-final-select-authorization.json).

Final local validation passed: 18-entry plan registry; scoped diff check;
evidence JSON parsing; Markdown links/whitespace; local transport syntax;
final SELECT P0/read-only/budget assertions; original six evidence hashes;
source delta reconciliation. Global diff check still reports the unrelated
Operations blueprint EOF blank line (now line 748 after concurrent work).
Root blueprint remains above the existing 4,000-byte governance cap. These
existing documentation issues were not repaired. No application tests were
needed for this documentation/read-only diagnostic work. Live validation is
limited to the exact captured diagnostics and cannot prove whole-gate closure.
