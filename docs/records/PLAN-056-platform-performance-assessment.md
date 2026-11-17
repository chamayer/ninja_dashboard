# PLAN-056 — Platform performance evidence

## Current direction — step 4; further interaction investigation deferred

User deferred resource-interaction investigation until larger demonstrated
defects are fixed. Root TODO.md owns resume conditions. Proceed to step 4 remedy
comparison/sequencing; incomplete interaction attribution is not a prerequisite.
No runtime/test implementation is approved. A [bounded correlation protocol](PLAN-056-resource-correlation-execution.md)
with full-visibility metadata and host/backend counters was approved for one
attempt. At 23:27:41 UTC it passed visibility/read-only checks, then stopped
before sampling because no reviewed Job was running. Exit 3; exact hash-checked
cleanup confirmed. No retry, forced work or runtime/test/data changes. Step 3
remains incomplete and deferred; the protocol record owns the attempt evidence.

## Big-picture step 4 — recovery-path comparison complete

The [comparison](PLAN-056-recovery-path-comparison.md) recommends the bounded
Coverage lifecycle join correction as the first slice for approval, followed
by relationship-history equality suppression as a distinct candidate with
unmeasured runtime benefit. It compares reader work, CVE difference writes,
shared publication, capacity/concurrency and retention, preserving freshness,
security and population contracts. A concrete Coverage runtime/test scope and
validation gates are prepared; no fix is adopted or implemented.

Git/source review corroborated the checkpoint; existing runtime work is preserved.
No external request, tests, configuration or data changes. Original assessment
items 6–12 remain open/partial, 2/4 deferred and 3 unavailable. Next: obtain
approval for the proposed Coverage slice or select an open assessment frontier.

## Big-picture step 3 — resource-evidence synthesis complete

The [resource-interaction review](PLAN-056-resource-interaction.md) reconciles
retained host/HTTP/database/Job windows and Coverage-specific process/actual-plan
evidence. Coverage is CPU-heavy in its attributed backend; sampled host CPU/RAM
headroom coexists with widespread slow pages and global buffer/temp work.
This supports considering work reduction before selecting capacity/concurrency
changes. It does not prove background Jobs cause each slow response or exclude
other bottlenecks. Full-visibility Coverage snapshots do not remove the earlier
runtime-role visibility limits for other workloads.

Local item-5 capture arithmetic corroborated the retained totals and grouped
counter deltas by request pair, explicitly as global interval differences.
No SQL/Job attribution inferred from these differences. Required follow-up
properties are recorded conditionally; no new production pass or approval
request is pending. Reviewed connection labels do not identify individual Jobs
or HTTP requests. Next: step 4, compare recovery paths with unresolved wait,
I/O/spill ownership and phase-cost gaps retained as decision/validation gates.
Original assessment items 6–12 remain open/partial. Documentation checks pass;
no runtime/test/schema/configuration or production changes.

## Big-picture step 2 — background amplification complete

Local [amplification review](PLAN-056-background-amplification.md) traced the
actual workflow guards and scope expansion. Crucial distinction: no pending
Software targets returns whole-fleet scope; it does not reach the empty-title
early exit. An existing test asserts that contract. Title-scoped finding work
still computes tenant readiness and publishes full exposure. Broad relationship
history and CVE replacement remain concrete write mechanisms; their production
contribution is unmeasured. Required timestamp freshness, time-relative expiry,
generation-fenced targets, queue coalescing and evaluator checkpoints constrain
what can safely change. Checkpoint targets are not hard statement/lock deadlines.

Source ASTs match HEAD; existing assertions reviewed, no tests run or changed.
Registry/whitespace/blueprint checks pass. No production command, Job, browser,
runtime or schema change. Next: big-picture step 3, distinguish resource
interaction using retained evidence and the minimum decision-relevant gaps.

## Big-picture step 1 — shared-work map complete

At the user's selection, local review connected page readers, Job producers,
shared calculations/stores and refresh boundaries in the
[shared-work map](PLAN-056-shared-work-map.md). It distinguishes navigation,
source metadata/lifecycle, Computer/ownership state, findings, software and
patch/activity work from page-specific access paths. AST checks confirm the
reviewed handlers and Job paths match HEAD, except preserved local Home edits;
earlier Issues/Software helper changes remain uncommitted and unadopted.

The current Jobs classifier skips empty title scopes and refreshes safety only
for whole-fleet reconciliation; the older main entry point behaves differently.
Do not infer scheduled work from that older path. Collection-derived projector
failure catches also qualify the documentation's completion invariant; the
discrepancy is recorded without choosing a behavior change. This map proves
dependencies, not per-path cost or a universal cause. No external request,
browser, new test or runtime edit. Registry/whitespace/size checks pass.

Next is big-picture step 2, background amplification and the specific unknowns
that could alter recovery design. The original assessment items 6–12 remain
open/partial; completing browser/network timings is not a prerequisite here.

## Item 5 — representative filter measurements complete

One bounded pass at 21:54:44–21:55:38 UTC completed all four selected first/
repeat pairs: Computers/Windows 2.620/1.305 s; Source Records/agent.rmm
5.574/5.392 s; Patching/server 3.734/3.732 s; Software/high risk 18.080/12.589 s.
All eight full HTML responses and exact server-completion markers were HTTP
200. Installed-source gates passed. Logout and hash-verified exact diagnostic
cleanup/absence confirmed; wrapper exited 0. No runtime or test changes.

These are configured-admin internal-loopback first/repeat timings with unknown
worker/cache state and concurrent resolver/evaluator work. They do not certify
filter populations, CSV, browser rendering, external-network timing or per-query
resource shares. Software remains slow under the selected risk filter; no
cause or new remedy is selected from this timing alone. See the
[execution record](PLAN-056-filter-variants-execution.md) for scope, counters,
hashes and limits. Item 5 complete for representative scope; next is item 6.

## Numbered checklist restored

The original [12-item assessment checklist](PLAN-056-assessment-checklist.md)
is restored with evidence-qualified status. Next is item 5, representative
supported filter variants. Item 1 is complete; items 2 and 4 are deferred to
post-fix verification; item 3 is unavailable. Items 6–12 remain open/partial.
The earlier next-action direction to a final remedy comparison was premature
and is superseded by this checklist. Static writer findings add candidates;
they do not finish runtime write/refresh attribution or the assessment.

## Current continuation — cold timing deferred; writer review complete

User deferred outstanding item 4 (controlled cold navigation) until post-fix
verification. No extra server or request was started; no method approval is
pending. The response target remains required after a fix.

The [write/freshness review](PLAN-056-write-freshness-review.md) completed the
next local task-6 slice. A nonzero relationship endpoint-resolution result
triggers an UPDATE of every visible open relationship-history row, without a
changed-ID or equality filter. This is confirmed code-level amplification,
not measured live cost or attribution of prior counters. Preserving broad
repair scope with an equality guard is a narrow candidate for later review.

The review also confirmed readiness freshness controls exposure expiry;
requirement evaluation time is displayed; unchanged CVE results are still
replaced; and time-relative materialized views prevent simple no-insert or
unchanged-membership refresh suppression. No implementation or architectural
decision was made. Next: draft the platform recovery candidate comparison
using this evidence and the confirmed read bottlenecks. Live per-job, lock and
refresh costs remain gaps; no new external observation was performed.

## Task 6 — Local writer and contention attribution (2026-11-10)

Read-only source review against the current checkout and retained runtime
counters identified several mechanically recurring write paths. These are code
findings, not measured current rates or proof that any one path caused observed
latency:

| Writer/path | Code behavior | Evidence and limit |
| --- | --- | --- |
| Requirement state (`0332`, evaluator) | `write_device_requirement_state` deletes every selected tenant/device row, then reinserts desired rows with `evaluated_at=now()`; no equality guard. | Runtime counters previously showed about 14.70M inserts and deletes against about 20k live rows. Scope/run attribution unavailable. |
| Software readiness (`ingest/software_readiness.py`) | Computes a tenant snapshot, upserts all rows and overwrites `assessed_at`; removes rows absent from the new snapshot. | Prior counters: 32.13M updates, 82.5k estimated live. Not a per-run rate; freshness may be part of the contract. |
| CVE matches (`ingest/intel/matcher.py`) | Deletes/rebuilds the tenant match set in one transaction, then compares old/new sets and queues downstream work only when content differs. | Prior counters: 58.76M inserts/60.31M deletes, about 655k live. Existing CPE/CVE lookup optimization reduces computation, not this replacement write pattern. |
| Relationship evidence (`ingest/relationships.py`) | Upsert advances `last_observed_at` on repeats; version increments only on changed material hash or reactivation. | Prior current/history counters were large, but versions and timestamps do not establish wasted writes; observation time is visible data. |
| Software inventory (`ingest/inventory/software.py`) | Delta path distinguishes unchanged rows for history heartbeat and feeds current-row upsert; `last_observed_at`/`refreshed_at` advance. | Write semantics include freshness. Need reader/age requirements before proposing separation or suppression. |
| Activity summaries | Successful activity ingestion refreshes three materialized views; raw event insert is conflict-safe and software trigger events are discarded after enqueue. No retention delete is in the ingest path reviewed. | Prior record cites 774k/7 GB in October; current size, refresh duration and table age distribution are unknown. |

PLAN-054/ADR-0056 establishes an exclusive tenant findings guard around shared
mutations, with API streaming outside it; resolver promotion is batched at ten
records per transaction. This bounds batch size, not run duration. Task 3's
runtime role could not see other-session wait/timing detail. Its one-minute
sample had zero deadlock delta; task 4's page window also had zero new deadlocks.
Neither establishes current lock stability or wait cost. No whole-job identity
or per-run write delta is available, and cumulative statistics have no common
reset epoch. Do not turn accumulated tuple counters into rates or infer all
updates are unnecessary.

Task 6 remains partial: local high-churn paths and unknowns are mapped, but
current write rates, job contribution, refresh cost, lock waits, and the effects
of freshness fields are not attributed. Any follow-up runtime observation needs
a separately reviewed bounded protocol and explicit approval. No writer,
retention, lock, or compaction change is selected.

## Task 7 — Requirements review across transferred frontiers (2026-11-10)

Review against `docs/requirements.md` and the superseded plans distinguishes
these commitments from proposal targets:

| Frontier | Requirement/decision status | Consequence for performance work |
| --- | --- | --- |
| Home | Retained accepted target: ordinary response at or below 1.5 s; hard maximum under 2 s, including cold navigation. Home summary values may be up to 60 s old. | Freshness allowance can support a short cache, but a cache hit alone cannot satisfy the cold target. No event queue or complex contribution ledger is preselected. |
| Operations populations | Preserve tenant and client scope, independent-action selection, source authority, current Coverage counts, and supported trends (at most 30 days where history exists). Coverage has no separate Home trend or added verdict history. | Faster aggregates must keep owner definitions and cannot substitute raw finding counts or unsupported event trends. |
| Filters and export | Complete filtered CSV and population/filter semantics are retained as existing PLAN-044 obligations. | SQL page limits or deferred details must not truncate CSV or change membership. |
| Source Records | No explicit latency SLO in root requirements. PLAN-048's first-page-under-1-s warm target is an inherited proposal. | Diagnose each slow component; optional facets are candidates to defer only with a clear completeness/freshness contract. No JSON removal or schema design is adopted. |
| Activity history | Readers include newest-100 device timeline and user-bounded patch search. No retention period is specified; three summaries refresh after activity ingestion. | Retention is a product decision, not a tuning default. Keep all events until a period and payload policy are approved; measure view needs first. |
| Storage/write freshness | Requirements preserve raw payload where needed, source fidelity, durable state, and trustworthy reporting. | `last_seen`, `evaluated_at`, `assessed_at`, and source freshness cannot be dropped or made stale without reviewing their displayed meaning and a replacement. |
| Capacity/configuration | No numerical host or PostgreSQL sizing target is established. The host is shared with other services. | Memory/work_mem/host changes require measured capacity and cross-service risk review; no blind increase. |
| Findings index | PLAN-049's tens-of-milliseconds acceptance applies to its candidate `/devices/` access path, not Coverage `/inventory/computers/`; candidate branch/migration is not adopted. | Re-evaluate only after read attribution and migration-order review; no universal page target inferred. |
| Lock coordination | ADR-0056's tenant write guard and source/ownership coordination are accepted correctness contracts. | Do not remove or bypass the guard for speed. Measure bounded transaction and wait costs in an authorized environment. |

Task 7 remains open for review of remaining route-specific requirements and
tradeoffs. No target has been waived. An old approval to implement a slice does
not approve it under the consolidated plan; any new or resumed implementation
needs the applicable PLAN-056 approval. No alternative is selected here.

## Task 8 — Provisional evidence ranking (2026-11-10)

This ranks investigation priority, not approved fixes. Confidence refers to the
existence of the observed symptom, not proof of its internal cause.

| Rank | Frontier | Evidence and confidence | Candidate direction / decision gate |
| ---: | --- | --- | --- |
| 1 | Home latency | High confidence: deployed configured-admin GETs were 8.983 s first and 6.828 s repeat versus retained ≤1.5 s ordinary / <2 s hard target. Source inventory completed in 1.716 s; Issues, Patching and Software Home readers each hit a 3 s statement deadline. Coverage completed in 0.254 s once. Issues and Patching plans give estimates only and do not prove actual cost shares. Sources, Jobs and shared context remain unmeasured. | Attribute remaining Home readers/context before choosing simplification/cache/summary. Verify a cold request and freshness/security behavior. No specific remedy is selected. |
| 2 | Coverage | High confidence: route timed out at 20 s; Hudu lifecycle SELECT hit 3 s. Medium confidence for lifecycle access path: correlated candidate plan narrows estimated lifecycle subtree 85,625→19.13 and whole plan 161,011→75,029; three-ID parity passed and full candidate read took 0.374 s. | Promising query-shape candidate, but no full original/candidate parity or page replay. Requires end-to-end semantics, editable-policy, tenant, and full-page validation before adoption. |
| 3 | Sources / Source Records | High confidence that two distinct statements hit 3 s limits. Medium confidence for broad scans/sorts from estimated plans; low confidence on function/group-mapping shares. | Separate read attribution by statement and consumer; preserve record population, source fidelity, and masks. Source Records facets may be deferred only with an explicit completeness/freshness contract. |
| 4 | Write churn | High confidence that several code paths replace or refresh rows; low confidence on current contribution because counters are accumulated, reset epochs differ, and no per-job delta exists. | Observe bounded per-run writes and freshness/lock impact before considering equality guards, timestamp separation, or refresh changes. No compaction before remeasurement. |
| 5 | Host/database capacity | One-minute sample shows active swap and high DB reads/spills, but no whole-host CPU or RAM exhaustion; statement identity and physical I/O are unknown. | No memory/host tuning conclusion. Require statement and cross-service capacity attribution first. |
| 6 | Activity retention | Historical 774k/7 GB evidence and unbounded retention proposal; current volume and reader/refresh costs unverified. | User must set retention and payload policy after read/age/size measurements. No deletion period inferred. |

No proposal is discarded or approved by this ordering. Task 8 remains
provisional until task 5/6 attribution and remaining requirements review narrow
the causes. The Home Issues plan now confirms broad planner estimates but no
actual cost share. Next: review this plan with the remaining Home reader gaps
and choose a separately bounded next observation. A separate Patching reader
pass hit its statement deadline; Coverage, Software, Sources and Jobs remain
unmeasured. Implementation sequence remains unapproved.

## Task 5 — Home reader component pass (2026-11-10)

After explicit approval of the prepared
[Home component protocol](PLAN-056-home-components-execution.md), one
read-only repeatable-snapshot pass ran on am-ch-01 with backend 358011. The
ten deployed source-module hash gates passed. Device policy took 0.027 s,
Clients 0.016 s, Computers 0.271 s, and source inventory 1.716 s. The Issues
summary/attention component hit the 3-second statement timeout at 3.019 s
(57014); the collector stopped. Patching, Coverage, Software, Sources, and Jobs
were not attempted. Connection closure and hash-verified cleanup of exact
container/host files and the empty directory were confirmed. No retries,
business changes, HTTP/session, Jobs execution or other-work cancellation.

This attributes a statement deadline to Home's governed Issues reader, not an
internal plan node or the full 8.983/6.828 s Home requests. The completed source
inventory component time is one pass only, not an HTTP breakdown or comparable
benchmark. Shared context, navigation badges, rendering, and remaining summary
components are unmeasured. Task 5 remains partial; no fix authorized.

## Task 5 — Home Issues plan (2026-11-10)

After explicit approval, one non-ANALYZE EXPLAIN of the exact deployed
`home_data()` aggregation completed in 0.185 s. Source hashes passed; the
collector emitted 59 nodes without truncation and confirmed connection closure.
The root Append estimates 6,369 rows at total planner cost 103,658.72; a
visible branch estimates 54,825 findings through a bitmap heap scan using
`idx_findings_status_severity`, with multiple aggregate/unique branches. Planner
cost and row estimates do not establish execution time or identify which node
caused the component statement timeout. Tool display clipped the complete node
serialization, so only visible metadata is retained. Details:
[Home Issues plan](PLAN-056-home-issues-plan-execution.md).

Exact host/container copies and empty directory were hash-checked, removed and
confirmed absent. No retry or ANALYZE is authorized. Task 5 remains partial;
no fix selected.

## Task 5 — Remaining Home readers (2026-11-10)

After separate explicit approval, the remaining-reader pass ran on am-ch-01
with backend 358860. Device-policy dependency completed in 0.025 s; Patching
hit the 3-second statement deadline at 3.009 s (`QueryCanceled/57014`). The
collector stopped; Coverage, Software, Sources and Jobs were not attempted.
Connection closure and hash-verified cleanup of exact temporary copies and the
empty host directory were confirmed. No retry or application/data/configuration
change. This attributes a deadline to the Patching Home reader, but not to an
internal query node or the full Home request. Details:
[remaining-reader execution](PLAN-056-home-remaining-execution.md).

## Task 5 — Patching Home query plan (2026-11-10)

After separate explicit approval, one non-ANALYZE EXPLAIN completed in 0.079 s
with backend 359561. It returned 52 nodes without truncation and confirmed
connection closure. The main branch estimates scans of devices (6,260 rows),
current patching scope (6,391), sessions (19,857) and ownership (5,781), plus
an activity scan estimated at 2,850 rows. The patch outcome lookup uses its
primary-key index. These estimates do not explain actual runtime or the earlier
statement timeout. The aggregation was not executed. Runtime source gates
passed; exact temporary copies were hash-checked and removed. No retry or fix.
See [the plan execution record](PLAN-056-home-patching-plan-execution.md).

## Task 5 — Next three Home readers (2026-11-10)

After the user's approval for three checks, one bounded runtime-role pass
measured Coverage in 0.254 s. Software then hit its 3-second statement
deadline at 3.010 s (`57014`); stop-on-error left Sources unattempted. The
collector confirmed connection closure and exact temporary cleanup. This is
one direct-reader result, not an HTTP breakdown. Static review separately
found the current working-tree Home context reuses Issues count but may query
the independent Patching badge on a cache miss; cache state is unknown. See the
[three-reader record](PLAN-056-home-next-three-execution.md) and
[shared-context review](PLAN-056-read-attribution.md#home-shared-context-and-remaining-reader-review--local-static-2026-11-10).
Next: a separate plan-only Software check requires its own approval.

## Task 7 — Source Records requirements review (2026-11-10)

Reviewed `docs/requirements.md`, the current `source_records` reader, the
PLAN-048 proposal and the timed-read evidence. Platform requirements support
multi-source evidence, relationship/identity review, trustworthy filtering and
tenant isolation; they do not set a Source Records latency target or require
every global facet to load synchronously. PLAN-048's under-one-second warm goal
is inherited proposal language. Full filtered CSV remains an explicit reader
behavior pending a deliberate requirements decision.

The default page-row SELECT itself hit the 3-second deadline, but no node cost
was isolated. Facet plan estimates are not runtime measurements. Keep the full
population and security semantics; consider deferred/on-demand facets only if
their completeness and freshness are clear, and consider keyset navigation
only if deep offsets are implicated. Cache/summary designs add invalidation,
tenant and write-cost duties. No remedy was chosen, no acceptance target waived,
and no further external read authorized. Task 5 is still partial; write
attribution (task 6) and requirements review of remaining frontiers are open.

## Task 1 — Local inventory (2026-11-09)

Task complete: local inventory and unknowns recorded. This is not a diagnosis
or current production baseline. No production access, Docker startup, jobs,
migrations, tests or benchmarks were performed. Runtime code was not changed.
Sources: current files, Git content/history/local refs, the standard-library
`shared.jobs_registry.schedule_definitions()` declaration, and retained records.

### Git and release state

- Current branch `master`, HEAD `ca00938a` (Patching outcome counts). Locally
  cached `origin/master` and `a-m-rose/master` also name that commit; no fetch
  was performed. This establishes neither remote nor deployed state today.
- Root VERSION and newest CHANGELOG heading agree on 0.144.10. Their latest
  update is `d139bacb`; HEAD contains subsequent Home changes and migration
  0406/SQL 119 without a corresponding release entry. Reconcile metadata only
  when a release is approved, not during this assessment.
- One registered worktree: current checkout. No staged changes. Preserve all
  existing modifications and eight untracked `.plan044_*_probe.py` diagnostics;
  none is implicitly approved for another run.
- Existing runtime differences from HEAD: compact Home Issues SQL, Home cache
  timing in middleware, four tenant-keyed Home summary caches, simplified
  installed-title count/card, and a freshness notice. Existing test changes
  cover dashboard/cache, Issues and Software. Their earlier validation claims
  are historical; this inventory did not rerun them or establish deployed parity.
- `git status` also flags migration 0406 and its batch-source test, but ordinary
  and whitespace-insensitive diffs show no content changes. Do not assume they
  contain a new schema revision or normalize them during inventory.

### Migrations and packaging

| Area | Verified in local repository | Still unknown externally |
| --- | --- | --- |
| Django | Latest file 0406, depending on 0405; additive tenant-checked security-definer bulk attribution function with explicit grants/revocations | Applied migration set, deployed function body and roles |
| Ingest SQL | Latest file 119, committed at HEAD; patch outcome counts table, maintenance trigger/function and runtime read grants | Ledger, installed trigger/body, current summary parity and overhead |
| Index candidate | Branch `plan049-active-findings-index`, commit `4cb502e0`, has index/model/page-reader/test changes; not an ancestor of HEAD | Whether equivalent access paths exist live; old branch migration 0404 conflicts with current chain |
| Operations image | Copies config/apps/templates/shared, manage.py and entrypoint; changed runtime files and migration are included | Built image and runtime code identity |
| Ingest/worker image | Copies ingest/sql/shared/VERSION; worker uses same build with `python -m ingest.jobs_worker` | Built image identity and current processes |
| Startup | Operations applies Django migrations before Gunicorn; ingest applies SQL migrations in main startup | Startup completion and currently applied versions |

Operations Dockerfile's comment says Gunicorn precedes migration completion,
contradicting entrypoint execution order. Use executable code for this local
inventory; leave comment correction for reviewed remediation. A push would
trigger deployment and pending migrations, so local presence is not evidence
that a migration is safe or pending on production.

### Request and service topology

Compose declares Postgres, ingest, Jobs worker and Operations; Operations exposes
3002 and loopback 8091, matching entrypoint binds. Gunicorn code defaults are
3 gthread workers, 4 threads each and a 60-second timeout; actual overrides are
unknown. Tenant middleware wraps non-exempt requests in a database transaction;
health/static/schema routes are exempt. Tenant/security behavior must survive
any redesign. No custom CACHES setting is declared in current settings; the
Home cache therefore uses Django's process-local default in this configuration.
Actual deployment settings and cache occupancy are unverified.

Compose sets Postgres shared-memory mount size to 1 GB; that is not
`shared_buffers`. No tracked Postgres memory-tuning configuration or Compose
CPU/memory limits were found in the inspected service definitions. Live values,
host workload, container overrides, connection capacity and resource pressure
must be measured in task 3. Historical 128 MB buffers/full swap are not current
facts; occupied swap alone does not prove active swapping.

### Scheduling and dependency topology

`shared/jobs_registry.py` declares raw schedules AND filters them through
`schedule_definitions()`. The effective local catalog has 15 tenant schedule
entries. Raw declarations are not a list of independently running timers.

| Effective schedule group | Local declaration; not live cadence |
| --- | --- |
| Ninja enrichment | PATCH_INGEST_SCHEDULE_HOURS, falling back to INGEST_SCHEDULE_HOURS (default 1 hour) |
| Ownership | Dirty catch-up every 10 minutes; full sweep every 24 hours |
| Software | Full classification default 24 hours; enqueue-orgs default 24 hours; queue drain default 5 minutes |
| Actions and recovery | Source actions every minute; run-log recovery every 30 minutes |
| Health and findings | Platform health every 30 minutes; source-record assessment every 5 minutes |
| Notifications | Dispatch cadence and digest hour from configuration |
| History retention | Daily hour from configuration |
| Intelligence projections | Capability/category cadences from configuration |

The raw matcher, resolver and main evaluator periodic declarations are filtered
out of the effective independent catalog because they are dependent steps.
Source-owned declarations are also excluded. This does not disable these jobs:
dependency revisions and manual requests can invoke work, while per-binding
source refresh schedules come from database configuration. Reconciliation reads
binding/instance enablement and `interval:N` cadence; no live bindings were read.
Scheduler heartbeat records a 60-second poll; scheduled admission is gated by
SCHEDULED_JOBS_ENABLED (code default true; dev Compose forces false). Source
revisions, successor fan-out, coalescing and database resource claims must be
included in observation. Actual enabled schedules, overrides, queue depth,
running jobs, resource limits and manual workload remain task 3 unknowns.

### Transferred work reconciliation

| Fragment | Verified local disposition | Unfinished evidence/work owned by PLAN-056 |
| --- | --- | --- |
| 041 CPU/matcher | Matcher fixes already committed in ancestor `297d6451`: 20,000-row/256-entry CPE cache and 500-key CVE batches | Old plan's release-pending checkpoint is stale. Verify deployed code and completed full-run outcomes; HOST-CPU record exists but does not demonstrate current performance. DMARC deployment remains a historical sibling-service claim. |
| 044 pages/Home | Home changes and SQL 119 are in HEAD; further Home cache/Issues/Software changes remain local | Preserve agreed semantics and old ≤1.5 s/under-2 s cold Home goal pending explicit requirements review. Last recorded deployed Home 9.090 s is historical, not a new baseline. Coverage/page/CSV obligations remain in scope. |
| 047 write churn | Ready proposal and writer inventory leads retained; no implementation claimed by this task | Verify present writers, change guards, timestamps, refreshes and actual write volumes before selecting a remedy. |
| 048 JSON reads | Typed-fact proposal/ADR-0055 remains a proposal; no new migration implementing it at current chain tip | Verify current consumers, costs and proposed-field parity; adoption and locking rehearsal remain undecided. |
| 049 active index | Separate candidate branch exists; no registered old worktree; old migration number conflicts | Reassess benefit before adoption; rebase/renumber only if selected, preserving page population and RLS. |
| 050 capacity | Historical configuration evidence retained | Current host/DB capacity and workload attribution entirely unverified. |
| 053 activities | Retention proposal retained; no implementation established here | Inventory reader needs, payload/age volumes and rollup costs before any retention decision or delete. |
| 054 deadlocks | Subsequent coordination releases appear in current history | Source document says release pending while registry records deployment; verify current locks, scheduled recovery and waits. ADR-0056 remains an existing contract. |

This inventory does not certify that no relevant changes exist elsewhere in
history. Task 5/6 trace current readers/writers before choosing designs.
PLAN-051 obsolete writers and completed PLAN-019 retention follow-ups remain
dependency inputs; unrelated cleanup is not automatically authorized.

### Evidence gaps and task 2 inputs

1. No current production baseline, applied migration list, image identity,
   host resource sample, enabled-schedule inventory or queue/lock snapshot.
2. Referenced PLAN-042 page-load and PLAN-044 validation records were not found
   at their linked paths or in current tracked filenames. Their quoted results
   are secondhand retained claims; do not invent a replacement baseline.
3. Existing production samples differ by date, permission, load, query revision
   and cache state. Component timings are not an additive request breakdown;
   successful unit checks do not prove speed, load capacity or live freshness.
4. Representative routes must include Home, Clients, both /devices/ and Coverage
   Computers, Issues, Sources/Source Records, Software, Patching, Settings and
   Jobs; choose bounded filters/roles in task 2. Include shared navigation work.
5. Observe background dependency chains and shared host services alongside pages;
   do not trigger full jobs just to build a baseline. Read-only collection must
   avoid customer payloads, credentials, unbounded queries and observer overload.

### Validation

Registry validator and `git diff --check` pass. Shared schedule enumeration
imported only the standard-library registry; no application settings, database
or external service was initialized. Runtime tests are unnecessary for these
documentation changes. Next: task 2, a concrete bounded measurement protocol.

## Task 2 — Measurement protocol (2026-11-09)

Complete: [bounded protocol](PLAN-056-measurement-protocol.md) defines task 3
metadata plus one passive 60-second resource window; task 4 sequential first/
repeat HTTP observations for 13 route/role pairs; and later attribution gates.
Limits include one SQL observer, one HTTP request, statement/lock deadlines,
10-minute task 3 and 15-minute/40-request task 4 budgets, privacy controls and
stop rules. Task 4 follows review/authorization after task 3; no external checks
were performed while preparing this protocol.

Verified route declarations against operations/config/urls.py. Read operational
access instructions and the shared helper implementation without loading private
profiles. Reviewed existing Home/activity probes: Home writes temporary sessions
and selects an existing user, while activity prints SQL text. Neither is approved
for this protocol. Use existing authorized sessions and redact at collection;
missing access or instrumentation stays an explicit gap.

Cold-cache state and individual request/backend correlation may be unavailable;
the protocol records that limitation instead of claiming a cold acceptance result
or canceling an ambiguously attributed statement. No runtime instrumentation,
session creation, performance experiment or production mutation is authorized.
Documentation contradiction about a separate redeploy is recorded in the
protocol; root AGENTS.md takes precedence. No deployment is in scope.

Registry and whitespace checks pass; no runtime tests needed for documentation.
Next: task 3, prepare/review exact diagnostics under this protocol and obtain
explicit external-observation authorization before running them.

## Task 3 — Diagnostics prepared; external gate pending (2026-11-09)

Prepared the database and host collectors plus the [execution review](PLAN-056-task3-execution.md).
Local profile metadata confirms `am-ch-01` provides SSH; no connection was made
and no private configuration values were printed. Nine metadata queries and
five bounded SQL samples use the existing runtime role; the host script captures
one resource window and selected image/source identities. Temporary transfer
and cleanup require the same explicit approval as this observation.

Python AST/Ruff/format, Git Bash shell syntax, registry and whitespace checks
pass. SQL execution, live permissions and runtime compatibility remain untested.
Known collection limits and omitted follow-ups are explicit in the execution
review. Task 3 is not checked off: next obtain approval, execute once, and review
results/gaps. No application code was changed or production accessed.

## Task 3 — Approved observation completed (2026-11-09)

User explicitly approved the prepared production observation and temporary-file
transfer/cleanup. Ran once through the `am-ch-01` helper profile; host samples
22:30:18–22:31:18 UTC and SQL samples 22:30:19.889–22:31:19.868 UTC. Nine
metadata reads and five statistics reads completed without SQL error. Collector
emitted its completion marker, waited for the database child and exited 0.
No page requests, session creation, jobs, configuration changes, migrations or
business-data writes were performed. Temporary files were hash-verified before
execution/removal and confirmed absent afterward. Initial container cleanup as
runtime OS user was denied because docker cp created a root-owned file; used
container root solely to remove that exact reviewed temporary file. Database
observation always used the existing non-superuser/non-BYPASSRLS runtime role.

### Verified deployed state

- All four Ninja services reported running/healthy. Docker memory/NanoCPU
  settings were zero (no explicit limits in those fields), not zero available
  resources. Selected code hashes match HEAD `ca00938a`: views, Issues,
  Software, Patching, middleware, shared registry, Operations entrypoint and
  matcher. This does not certify every image file or prove the whole commit.
- Uncommitted Home cache/Issues/Software/middleware changes are not deployed.
  Runtime matcher includes the committed optimization; its whole-job improvement
  remains unmeasured. Runtime VERSION hash matches local 0.144.10.
- Django 0406 and ingest SQL 119 are applied. Bulk attribution function and
  patch-count table/maintenance trigger exist. Active-subject index is absent.
  Catalog existence is not a full function-body or summary-parity audit.
- PostgreSQL 16.14. pg_settings reports shared_buffers=16384 (8 KiB blocks,
  128 MiB), effective_cache_size=524288 (8 KiB blocks, 4 GiB), work_mem=4096
  (KiB, 4 MiB), maintenance_work_mem=65536 (KiB, 64 MiB), max_connections=100,
  random_page_cost=4. track_io_timing is off; pg_stat_statements is not installed.
  No instrumentation was enabled.
- Schedule page returned 50 of 53 entries, including disabled legacy entries.
  Sampled matcher/resolver/main-evaluator independent schedules were disabled;
  ownership, software, health, source-record assessment and source-refresh
  schedules were present/enabled. This is not a complete schedule census.
  Binding aggregation: 17 enabled bindings/instances, with 6 daily, 6 four-hour,
  3 six-hour and 2 hourly cadences. Latest worker/scheduler heartbeats were
  about 10/19 seconds old at metadata collection; 557 historical heartbeat rows
  exist, so stopped_at=null on an old row does not identify a live process.

Selected deployed hash prefixes (HEAD match): views `8701f537683d`, Issues
`181d9a86c285`, Software `d4d24dd70976`, Patching `49f78e79f416`, middleware
`013c61467e5a`, registry `45bb8ce8ac05`, entrypoint `9d58ff05b4b6`, matcher
`d7f7859b0d9c`, VERSION `18e92e334288`. Collector SHA-256 prefixes: database
`8852e6534500`, host `b0b5814f796c`.

### Resource and database observations

| Measure | Observed result | Interpretation limit |
| --- | --- | --- |
| Host memory | 62.80 GiB total; 31.18–31.59 GiB available across snapshots | Prior ~35 GB host evidence is stale; this window does not show RAM exhaustion |
| Aggregate CPU | 69.78% idle, 28.95% busy excluding I/O wait, 1.27% I/O wait from /proc/stat deltas | No whole-host CPU saturation here; individual workers/cores may still constrain work |
| Swap | About 8 GiB occupied; 547 pages in and 4,064 pages out over 60 s | Some active swapping exists, but occupied swap alone does not establish thrashing or causation; page size was not measured |
| Ninja Postgres Docker CPU | Five point samples: 106.96%, 103.92%, 108.99%, 171.76%, 42.05% | Docker 100% is approximately one core; these are point samples, not a minute average |
| Operations/ingest/worker | Mostly low CPU; Jobs worker briefly sampled at 99.99% | No job identity can be assigned from CPU alone |
| Database reads | +428,196 blocks, about 3,345 MiB at 8 KiB/block; +1,365,579 shared-buffer hits | Reads into Postgres buffers may come from OS cache; not a physical-disk-byte measurement |
| Temporary files | +5 files, +87,080,960 bytes (83.05 MiB) | Confirms spill work during the window; statement identity unavailable |
| Database activity counters | +276 commits, +1 rollback, +359 inserted/+599 updated/+55 deleted tuples | Includes normal workload and observer effects; asynchronous statistics are not an exact transaction ledger |
| Deadlocks | Cumulative 24, delta 0 | No new recorded deadlock in this minute; does not establish long-term stability |
| Connections | 6 initially/finally, 9 at one intermediate snapshot, including observer | Not near 100 at snapshots; no proof against transient connection waits |
| Root filesystem | About 898 GiB available | Database mount capacity not established |

The database read/temp deltas increased especially near the end of the window.
All sampled hot-table counters were unchanged for roughly the first 30 seconds;
only small finding/assessment changes appeared later. This minute did not capture
a major rewrite pass, despite substantial accumulated counters below.

### Accumulated write evidence (not minute rates)

Counters have no established common per-table reset epoch; database stats_reset
was null. Do not turn these figures into per-day rates or call every write waste.

| Table | Estimated live rows | Accumulated writes / autovacuum count |
| --- | --- | --- |
| cve_match | 655,086 | 58.76 M inserts, 60.31 M deletes / 624 |
| relationship evidence current | 33,281 | 41.13 M updates / 7,243 |
| relationship evidence history | 60,037 | 20.65 M updates / 5,619 |
| software readiness | 82,510 | 32.13 M updates / 2,038 |
| requirement state | 20,442 | 14.70 M inserts and 14.70 M deletes / 2,798 |
| patching scope current | 6,391 | 9.82 M inserts and 9.82 M deletes / 6,843 |
| session current | 6,391 | 9.99 M inserts and 9.99 M deletes / 6,358 |
| current software installations | 627,312 | 19.46 M updates / 204 |
| findings | 624,121 | 9.20 M updates / 39; estimated 115,878 dead rows |

These support prioritizing writer attribution in task 6; they do not prove which
writes were unnecessary or their contribution to current latency.

### Limits and next action

- Runtime role has no pg_monitor membership. Other sessions exposed application
  names but null state/wait/timing fields. Empty blocker output is therefore
  inconclusive, not evidence of no locks or active queries. Task 4 correlation
  needs an existing authorized monitoring role or existing request telemetry;
  do not grant privileges as a diagnostic shortcut.
- Oldest-first active/queued/stalled query returned old stalled rows, obscuring
  today's workload. No claim about the currently running job set is supported.
  Revise selection locally before requesting any follow-up observation.
- Initial tool output was truncated, losing portions of runtime/run/capacity
  metadata; no replay was performed. Retained metadata and samples support the
  findings above. Unknown capacity policy details remain open.
- Exact running Gunicorn arguments, node/core count, query identities, relation
  sizes, active dependency/claim reasons and physical I/O attribution remain
  unavailable. No authenticated page timing or load-capacity conclusion exists.
- Current evidence does not support treating whole-host RAM/CPU exhaustion as
  established. High database read demand, spills, small shared buffers and
  cumulative churn are investigation leads, not a chosen remedy.

Task 3's single bounded observation is complete with these explicit gaps. Next:
task 4 preparation—resolve existing authenticated access and request correlation,
review GET side effects and prepare the exact bounded request scope before its
external authorization. Prior task 3 approval does not cover page requests.

## Task 4 — Access/GET review and pilot prepared (2026-11-09)

User identified host .env credentials as the intended access path. Prepared
normal admin-login pilot and bounded access-log completion filter; see the
[execution review](PLAN-056-task4-execution.md). Credentials stay inside the
container; no synthetic sessions, user selection, bootstrap command or role
change. Normal authentication/session/last-login effects require explicit scope.
No production access occurred while preparing task 4.

Static review identified shared navigation costs even on Settings, Issues GET
session preference saves, Jobs automatic page refresh and the legacy Job status
redirect. The revised later matrix has 11 admin route variants, not ordinary-user
substitutions; Jobs uses refresh=off and redirect-only status is excluded.
Gunicorn gthread timeout cannot be assumed to terminate an individual request.
Use an exact non-secret query marker to demonstrate existing access-log completion
before attempting the full matrix; no SQL-backend attribution is claimed.

AST/Ruff/format, shell syntax, registry and whitespace checks pass; no runtime
checks or new test files. Task 4 remains open. Next: obtain approval for one
normal login, one marked Settings GET, logout, bounded filtered log reads and
temporary-file transfer/cleanup. Then review results before the main pass.

## Task 4 — Access/completion pilot succeeded (2026-11-09)

User's instruction to proceed followed the explicit pilot approval question.
Executed only that scope: normal configured-admin login using mounted
credentials, one marked internal Settings GET, normal logout, filtered completion
log read and temporary-script transfer/removal. No credential/session values,
response bodies, raw logs or customer records were returned. No fixes or other
page measurements were performed.

| Observation | Result |
| --- | --- |
| Pilot scope emitted | 2026-11-09 22:39:35.715 UTC |
| Settings result | HTTP 200; headers 1.783 s; complete body 1.783 s; 27,863 bytes |
| Result emitted | 22:39:39.347 UTC |
| Permission | Configured admin, normal credential authentication |
| Endpoint/cache | Internal loopback 3002; first observed, cache state unknown |
| Server completion | Exact non-secret marker matched existing Gunicorn GET access log, HTTP 200 |
| Logout | HTTP 302; session cookie cleared, confirmed by collector at 22:39:39.474 UTC |
| Collector | Exit 0; wrapper deadline not reached |
| Temporary artifacts | Hash-verified before execution/removal; host/container copies and empty host directory confirmed absent |

Collector SHA-256 prefixes: HTTP `9ba4165bb916`, completion filter `87ab8b248b1a`.
Normal login/session/last_login/access-log effects occurred as scoped; no
bootstrap, synthetic session, password reset, business-data mutation, job or
deployment. Cleanup used container root only for the root-owned temporary file.

This demonstrates a usable authentication and request-completion path without
extra database monitoring grants. It does not identify a backend/query, prove
cold latency, measure ordinary users, or establish platform performance. No
resource window ran simultaneously; task 3 resource samples cannot be attached
to this timing as if they were concurrent. Login/logout timings are not included
in the 1.783-second page measurement.

Task 4 remains open. Next: prepare the exact main collector for the 11-route
admin matrix and overlapping bounded passive observation; review scope before
external approval. The one-page pilot is not authorization for the full pass.
Registry/whitespace checks pass; no application changes.

## Task 4 — Full matrix prepared (2026-11-09)

Prepared [main-pass execution review](PLAN-056-task4-matrix-execution.md): eleven
fixed routes, two GETs each under the configured admin, one normal login/logout,
at most 44 read-only database snapshots and overlapping 15-second host sampling.
The helper reuses the proven pilot authentication with a new matrix callback;
the pilot's historical hash identifies the earlier executed version only.
Current-job snapshots select recent running/queued work, addressing task 3's
oldest-stalled selection gap. Other-session SQL visibility remains unavailable.

First failed page/timeout/query/observer flag ends the pass; exact completion
markers, local redacted capture, temporary-file cleanup and known limitations
are specified. Python syntax/import/route checks, Ruff/format, shell syntax,
synthetic log redaction/completion, registry and whitespace checks pass. No
external access or application changes during preparation. Task 4 remains open;
next obtain main-pass approval, execute once, and record actual results/gaps.

## Task 4 — Main pass stopped at Coverage timeout (2026-11-09)

User instructed next for the full page-measurement/resource pass. Executed the
prepared scope once with normal configured-admin authentication, mounted
credentials kept inside Operations, the fixed route order and stop-on-failure
rule. HTTP matrix and sampler started around 22:46:42 UTC. No business fixes,
jobs, deployments or configuration changes. This is a partial measurement,
not task 4 completion.

### Full HTTP observations

Internal loopback port 3002, configured admin, first-observed/repeat with unknown
worker/cache state. Response bytes matched within each completed pair; no HTML
contents retained. TTFB and complete times differ by at most 0.001 seconds in
these observations. Authentication and SQL snapshot time are excluded.

| Page | First complete time | Repeat complete time | Outcome |
| --- | --- | --- | --- |
| Settings | 1.962 s | 0.114 s | Both 200, 27,863 bytes each |
| Home | 8.983 s | 6.828 s | Both 200, 36,369 bytes each |
| Clients | 3.307 s | 3.160 s | Both 200, 160,229 bytes each |
| Computers `/devices/` | 2.059 s | 1.183 s | Both 200, 130,319 bytes each |
| Coverage Computers | Incomplete at 20.000 s deadline | Not attempted | Client TimeoutError; server completion unverified |

Coverage request started at 22:47:11.762 UTC and timed out at 22:47:31.763 UTC.
Do not describe 20 seconds as its completed response time. No subsequent page
GET was made: Issues, Sources, Source Records, Software, Patching and Jobs were
not attempted. Neither were variants or ordinary-user requests.

### Concurrent observation

Eighteen read-only snapshots (before/after nine attempts), maximum measured SQL
duration 0.045 seconds. Each sampled current-job page showed platform-evaluate
running, started 22:45:45.252 UTC, with no wait category. This is a job status
sample, not proof of CPU use, a lock-free job or a complete active-work census.
The selection is capped at 20 recent running/queued rows; other-session database
wait/query visibility remains unavailable under the runtime role.

| Marked request window | Global Postgres blocks read delta | Global temp bytes delta |
| --- | --- | --- |
| Settings first / repeat | 28,102 / 112 | 5,062,656 / 0 |
| Home first / repeat | 319,840 / 306,736 | 64,297,160 / 64,280,776 |
| Clients first / repeat | 88,959 / 92,791 | 0 / 0 |
| Computers first / repeat | 76,594 / 37,061 | 5,062,656 / 0 |
| Coverage deadline interval | 12,465 | 0 |

These are global asynchronous counters, including background evaluation and
other workload. They cannot be assigned wholly to the marked request; a long
in-progress statement may not yet have published statistics. In particular,
Coverage's small delta does not prove little work, a lock wait, or completion.
Buffer reads may be served by OS cache, not physical disk. Before the first
through after the ninth attempt, database deltas were +962,726 reads, +539,422
hits, +138,703,248 temp bytes in 14 files, +3 inserts/+99 updates/+3 deletes,
and no additional recorded deadlocks. No counter reset was observed.

Four host samples at 22:46:42/57 and 22:47:12/27 UTC overlap these requests.
Their 45-second /proc/stat interval was 63.02% idle, 34.86% busy excluding I/O
wait and 2.12% I/O wait; available memory stayed about 31.4–31.6 GiB. Swap-in
increased 1,009 pages, swap-out unchanged across those samples. Postgres Docker
CPU samples were 106.18%, 206.21%, 175.48%, 212.27% (100% approximately one
core, not host saturation). Measurements support tracing costly read work and
shared request/context costs, without establishing their causal shares.

### Completion, cleanup and limits

Eight successful markers matched the existing access log with status 200.
Coverage marker 9 was absent from both the immediate and final bounded checks;
the latter followed about 70 seconds of post-timeout observation. Its server
request/query may have ended without a log or may still have been executing;
no claim either way is supported. No cancellation, privilege escalation,
additional query inspection or further page request was performed.

Collector explicitly stopped after attempt 9, closed its database connection,
confirmed normal logout (302 with session cookie cleared at 22:47:31.856 UTC),
and host wrapper waited for the sampler then exited 1 for the measured failure.
This is not a wrapper timeout or an unknown collector lifetime. Session cleanup
is confirmed; Coverage server completion is a separate unresolved issue.

Temporary host/container files were hash-verified and removed after collector
completion; host observer.done removed, empty directory removed, container stop
flag absent. Container root was used only to remove root-owned temporary files.
Local redacted capture was parsed without tool-output truncation; aggregate
results above are retained, and the temporary capture is removed afterward.
Collector hash prefixes: auth `f25246f3e3b1`, SQL helper `8852e6534500`, HTTP
matrix `06cc29edb4b7`, host wrapper `76893d4509d5`, completion filter `56fe3a831797`.

Task 4 stays open. Next: prepare a bounded read-only check of Coverage completion
using an existing authorized monitoring path; do not grant privileges or assume
an empty runtime-role view proves completion. Resolve that uncertainty before
proposing a continuation for the six untouched pages. No automatic replay of
Coverage or main pass. Registry/whitespace checks pass; no application changes.

## Resume checkpoint — 2026-11-10

Verified Git status, active blueprint, registry and current diagnostic files.
Existing application changes remain preserved; task 4 is still incomplete.
Eight successful page measurements, Coverage's incomplete 20-second attempt,
confirmed logout/diagnostic cleanup and six untouched pages remain the checkpoint.
No new production observation has occurred on this resume. Next prepare a
bounded historic-marker/current-activity check, with an explicit review gate
before using a database monitoring identity other than the runtime role.
A fresh session is recommended after this preparation because the current
session is long. Resume from PLAN-056 and this evidence, not the transcript.

Prepared [Coverage completion review](PLAN-056-coverage-completion-review.md)
with a fixed historical-marker filter and read-only catalog SQL through the
documented existing ninja Unix-socket inspection identity. Its different
visibility/possible privilege requires explicit approval; it has not run.
Only system session metadata/known-shape booleans are returned, no query text,
payloads, business reads, grants, cancellation or new page GET. Shell syntax,
static SQL review, registry and whitespace checks pass. Next: fresh session,
verify checkpoint and request approval for that exact scope/identity.

## Resumed checkpoint — 2026-11-10

Verified HEAD `ca00938a`, working-tree status/diff, active routing and the two
prepared Coverage completion artifacts against their execution review. Existing
runtime/test changes remain untouched. The wrapper restricts historical logs to
the fixed interval/marker and the SQL returns bounded catalog metadata through
the explicitly gated inspection identity. No production access or page replay.
Task 4 remains partial; next obtain approval for the exact scope in the
[completion review](PLAN-056-coverage-completion-review.md).

## Task 4 — Approved Coverage completion check (2026-11-10)

User approved the exact completion review, including the existing `ninja`
inspection identity and temporary transfer/cleanup. Executed once through the
shared am-ch-01 helper. Catalog timestamps: 14:30:49.424–14:30:49.439 UTC.
Wrapper exited 0 and emitted its completion marker; no retries or fallback.

- Operations was running/healthy, started 2026-11-09 18:20:48.798 UTC;
  Postgres was running/healthy, started 2026-11-06 04:57:11.712 UTC. Neither
  reported container start bounds survival of the later Coverage attempt.
- Fixed historical interval/marker filter emitted
  `coverage_completion_not_observed_in_bounded_history`. This establishes no
  historical outcome; missing, rotated or truncated logs remain possible.
- Read-only catalog access confirmed matching database, superuser=true and
  can_read_all_stats=true. No grants, role changes or business reads occurred.
- The Operations application-name filter returned zero sessions. This is a
  current snapshot with full statistics visibility, not a record of past work.
  Local production settings declare that application name; deployed overrides
  were not audited here. No query was exactly attributed to the HTTP marker.
  Non-database work and differently labeled sessions remain outside this check.
- SHA-256 matched before execution and cleanup: wrapper `b5455f89d55c`, SQL
  `9aa35fc8820e`. Only those two host files were removed, the empty directory
  was removed with rmdir, and its absence was confirmed. No container files
  or credentials were transferred. No HTTP requests, cancellations, restarts,
  configuration changes or data mutations were made.

Disposition: historical Coverage completion remains unknown; no matching current
database session was observed. Do not replay Coverage or keep polling for its
past outcome. Task 4 stays partial. Prepare a separate bounded continuation for
Issues, Sources, Source Records, Software, Patching and Jobs, excluding Coverage
and completed pairs. New page/auth/resource observation requires approval of
that concrete pass. Preserve role/cache and attribution limitations.

## Task 4 — Six-page continuation prepared (2026-11-10)

Prepared the [continuation execution review](PLAN-056-task4-continuation-execution.md)
and three diagnostic variants for the six untouched routes: 12 maximum GETs,
24 runtime-role SQL snapshots, overlapping passive host observation and bounded
exact-marker completion checks. Excludes Coverage and completed pairs; original
executed artifacts remain unchanged. Normal login/logout/session housekeeping
and temporary transfer/cleanup are explicit in the new approval scope.

Local AST/import/route/stop-path, Ruff/format, shell syntax and synthetic log
redaction/prefix/index checks pass. Registry/whitespace checks pass. No application
or test edits, production access or new architectural decision. Task 4 remains
partial. Next: obtain approval for this concrete continuation, run once, record
actual observations and limits. Earlier observation approvals are not reused.

## Task 4 — Approved six-page pass completed (2026-11-10)

User explicitly approved the prepared continuation. Executed once through the
shared am-ch-01 helper, configured admin on internal loopback 3002, no Coverage
or completed-page replay. All 12 measured GETs returned 200 and matched exact
access-log markers in one bounded completion read. The collector emitted
matrix_complete=12, confirmed normal logout (302, session cookie cleared) at
14:46:14.901 UTC, and closed its database connection. Host wrapper waited for
the sampler and exited 0; no wrapper deadline, stop flag or retry.

### Page results

| Page | First complete time | Immediate repeat | Response bytes first/repeat |
| --- | --- | --- | --- |
| Issues | 5.287 s | 1.820 s | 88,877 / 88,877 |
| Sources | 11.661 s | 10.413 s | 81,018 / 81,018 |
| Source Records | 13.358 s | 14.142 s | 137,928 / 137,928 |
| Software | 12.135 s | 12.415 s | 47,143 / 47,143 |
| Patching | 8.000 s | 12.667 s | 125,231 / 125,234 |
| Jobs, refresh off | 1.299 s | 1.067 s | 60,412 / 60,412 |

Measured requests span 14:44:30.413–14:46:14.810 UTC; header/complete times
differ by at most 0.001 s. Authentication and SQL snapshots are excluded.
Different Patching byte counts are observed, not a demonstrated data defect or
parity result; response contents were not retained. Unknown worker/cache state,
admin-only access, no browser/JS/external network, and one pair per route remain
limits. Repeats are not proven cache hits. This window has different concurrent
work from the prior pass, so no before/after improvement claim is supported.

### Concurrent observations

All 24 runtime-role SQL snapshots completed; maximum 0.038 s. Resolver was
running throughout the sampled endpoints (started 14:43:12.449 UTC), while
platform-evaluate was queued with dependency wait. Source-record-assess was
also running by the final snapshot (started 14:46:01.595 UTC). These status
samples do not measure whole-job completion, CPU or database waits. Selection
remains capped at 20 recent jobs requested within 24 hours.

| Request pair | Global blocks read delta first/repeat | Global temp bytes delta first/repeat |
| --- | --- | --- |
| Issues | 62,027 / 26,669 | 14,098,432 / 9,027,584 |
| Sources | 627,498 / 756,968 | 5,070,848 / 5,070,848 |
| Source Records | 644,308 / 638,203 | 0 / 0 |
| Software | 981,570 / 468,337 | 128,144,018 / 159,385,471 |
| Patching | 167,939 / 230,252 | 5,070,848 / 31,241,453 |
| Jobs | 56,467 / 29,976 | 40,353,792 / 6,324,224 |

Across before_1 to after_12: +4,690,376 buffer reads (35.78 GiB at 8 KiB),
+8,974,685 hits, +43 temp files/+403,787,518 temp bytes (385.08 MiB),
+31 inserts/+240 updates/+8 deletes, no new deadlock. Stats reset remained
null at both endpoints. Counters are global/asynchronous and include background
jobs, other users and observation; they are not per-request attribution.
Buffer reads can come from OS cache and are not physical disk read bytes.

Eight host samples, 14:44:26–14:46:11 UTC, overlap the pass. Over that 105-second
/proc/stat interval: 68.07% idle, 30.13% busy excluding I/O wait, 1.80% I/O wait.
Available memory ranged 30.95–31.31 GiB. Swap-in rose 37,012 pages; swap-out
did not rise. Page size was not measured. Postgres Docker CPU samples ranged
102.10–411.37% (100% roughly one core), not a host CPU saturation claim or an
interval average. Physical-device disk counters were collected, but no device
topology/statement attribution or per-page disk-latency conclusion was established.

### Cleanup, validation and disposition

All five host and three container files matched reviewed hashes before
execution/removal (prefixes in the execution review). Removed only those files
and observer.done; rmdir removed the empty host directory. Host/container
absence and stop-flag absence confirmed. Container root was used only for
root-owned temporary-file cleanup, never SQL. Normal login/session/last_login
effects occurred as approved; no business fixes, jobs, grants, deployment,
configuration changes, cache flush or cancellation. Local redacted capture is
removed after preserving these aggregates. Registry/whitespace checks pass.

Task 4 remains open: the Coverage timeout is an unresolved diagnostic blocker,
not an accepted result. The historical HTTP outcome cannot be reconstructed
from the available bounded logs; the later empty application-name snapshot
does not explain the stall. No further polling or blind replay is proposed.

Local static trace identifies eight initial HTML-path SELECTs before inventory
assembly, plus page-scoped presentation queries and shared render/context work.
`fleet_coverage` loads fleet-wide requirements, Hudu inventory/lifecycle,
Computers, clients, presence, source observations, platforms and source counts
before Python filtering and pagination to 100 rows. This is confirmed code
structure, not measured attribution. Either SQL, Python assembly or shared
rendering could account for the stall; no specific statement has been proven.
Local Coverage and lifecycle-selector ASTs match HEAD. Prepared a
[component collector/execution review](PLAN-056-coverage-components-execution.md)
for the eight initial raw HTML SELECTs, with labels, own backend PID,
3-second server statement deadlines, stop on first failure and bounded diagnostic
process termination. No HTTP replay or app changes. AST/import, exact query
order/branch exclusion, lifecycle expansion, Ruff/format and documentation
checks pass locally; the probe has not run externally. Next: obtain explicit
approval, execute once and follow the measured failing query or later-phase
frontier. Do not close
task 4, waive acceptance or infer whole-platform recovery from the 12 successes.

## Task 4 — Coverage query frontier identified (2026-11-10)

User approved the exact component probe. Executed once through the shared
helper with the existing runtime role; deployed Coverage/selector AST gates
passed. Collector's own backend was 348894, giving exact probe attribution.

| Component | Actual result |
| --- | --- |
| Stored requirements/presence | Completed in 0.604 s, 19,037 rows |
| Hudu inventory/lifecycle | Server statement deadline; QueryCanceled/57014 after 3.012 s |
| Remaining six initial components | Not attempted under stop-on-first-failure |

First component started 14:55:26.837 UTC; failure and probe_finished at
14:55:30.453 UTC. The Hudu figure is an incomplete observation at its enforced
deadline, not a completed runtime or proof it alone caused the earlier 20-second
HTTP stall. This is a concrete slow-query lead. The 1-second lock timeout did
not produce lock-unavailable/55P03, but this does not establish absence of all
waits. No SQL text, result values or credentials were emitted.

Connection closure confirmed; exit 1 represents the measured query failure,
not a wrapper timeout. No retries, later components, HTTP, sessions, jobs,
grants, configuration/app changes or cancellation of another process/query.
The server canceled only the probe's own statement as approved. Both diagnostic
copies matched SHA-256 `39a97e8815ab...` before execution and removal; exact host/
container file and empty host directory removed and absence confirmed. Container
root was used only for temporary-file cleanup. Documentation checks pass.

Locally reviewed view definitions in migrations 0149/0158: Hudu JSON projection/
card existence and lifecycle lateral mapping lookup are leads; installed view
definitions, estimates and cost shares remain unverified. Prepared a
[one-plan review](PLAN-056-coverage-plan-execution.md) and whitelist-redacting
collector for one runtime-role EXPLAIN without ANALYZE of this exact SELECT.
Local AST/import, query selection, redaction/parent linkage/node-bound checks and
Ruff/format pass. No new external access during plan-check preparation. Task 4
remains open; next obtain that explicit plan-check approval before execution.

## Task 4 — Hudu access path recorded (2026-11-10)

User approved the one-plan check. Executed once through the shared helper using
the runtime role; source gates passed. Non-ANALYZE EXPLAIN completed in 0.141 s
at 15:01:14.472 UTC; 21 nodes, no truncation. Connection closure and exit 0
confirmed. Both reviewed files hash-verified before execution/removal and exact
host/container cleanup confirmed. No HTTP, row-query execution, retries, grants,
schema/config changes, jobs or other-work cancellation.

The [retained plan](PLAN-056-coverage-plan-execution.md#execution-outcome--2026-11-10)
has a left nested loop with broad lifecycle input estimated at 30,049 rows,
including observation/source joins and per-observation mapping LIMIT/sort work.
The Hudu side includes JSON relayed-card work. Top total cost 161,011.33 is a
planner estimate, not seconds; no actual loops or per-node runtime measured.
This supports investigating scope/parameterization before choosing a remedy.

Local contract review confirms lifecycle is editable shared policy (ADR-0011);
do not substitute Hudu's raw archive field. Prepared a separately gated
[candidate-plan check](PLAN-056-coverage-candidate-execution.md) preserving that
view, tenant/observation keys and left-join semantics in a correlated subquery.
OFFSET 0 tests a query-shape fence without removing rows or adding LIMIT. No
application edits or candidate adoption. Local source/join/projection checks,
Ruff/format, registry and whitespace pass. Task 4 remains open; next obtain
explicit approval for one candidate EXPLAIN without ANALYZE, then compare
estimated access paths. Runtime improvement and result parity remain unproven.

## Task 4 — Candidate plan narrows lifecycle access (2026-11-10)

User approved the exact candidate plan check. Executed once through the shared
helper/runtime role; source gates passed. Non-ANALYZE plan completed in 0.049 s
at 15:07:04.983 UTC, 21 nodes, no truncation. Exit 0, connection closure and
hash-verified host/container cleanup confirmed. No row-query execution or fixes.

The [retained candidate plan](PLAN-056-coverage-candidate-execution.md#execution-outcome--2026-11-10)
replaces the broad lifecycle branch with an observation primary-key lookup,
estimated one row. Lifecycle subtree cost: 85,625.27 to 19.13; whole-query cost:
161,011.33 to 75,029.22. Hudu population/JSON branch remains unchanged. These
are planner estimates, not measured speedup, actual loop counts or parity.

Prepared [bounded execution/parity review](PLAN-056-coverage-validation-execution.md)
and collector: at most three eligible observation IDs, original/candidate
restricted to those IDs in one read-only repeatable snapshot, then one full
candidate read only after nonempty multiset equality. Four maximum SELECTs,
3-second server deadlines, stop on first error/mismatch; no full-original rerun
or HTTP. Local source/population/guard checks, in-memory success/mismatch/timeout/
redaction/closure checks, Ruff/format and documentation checks pass. No app/test
changes or external access during preparation. Task 4 remains open; next obtain
explicit execution/parity approval, with candidate adoption still unapproved.

## Task 4 — Execution evidence and observation checkpoint (2026-11-10)

User approved the exact bounded validation. Ran once via the shared helper and
runtime role, source gates passed, backend 349843. One read-only repeatable
snapshot; all four SELECTs succeeded:

- Three eligible observation IDs: 0.167 s.
- Original restricted to those IDs: 1.602 s, three rows.
- Candidate on the same IDs: 0.006 s, three rows; complete result multisets equal.
- Full candidate, only after sampled parity passed: 0.374 s, 4,873 rows.

Reads spanned 15:15:58.537–15:16:00.687 UTC. validation_finished confirmed
connection closure, status/exit 0; no retry, deadline or SQL error. Three host
and three container copies matched reviewed hashes before execution/removal;
exact files/empty directory removed and absence confirmed. Container root only
removed diagnostics. No HTTP, app/schema/config change, job or other-work
cancellation. Details: [validation outcome](PLAN-056-coverage-validation-execution.md#execution-outcome--2026-11-10).

This is concrete execution evidence supporting a lifecycle-join remediation
candidate. The shared policy, tenant scope, views and original projected values
remain in use in the diagnostic variant. No application change is authorized.
Three-observation parity is not fleet-wide parity or edge-case validation;
full-page performance/security/freshness still require later verification.
Original-before-candidate order, cache and different observation windows prevent
a comparable-load speedup claim. No full-original rerun or page replay occurred.

Observation review: task 4's approved configured-admin collection is complete.
All eleven selected routes have an actual outcome: ten completed first/repeat
pairs, Coverage's stopped first attempt, plus aligned resource/job snapshots and
the separately attributed Coverage query checks. The Coverage failure remains
open for attribution/remediation, not accepted as passing. Its past HTTP result
is unrecoverable from the bounded logs; that fact does not erase the observed
client timeout or establish current server work.

Remaining obligations stay explicit: ordinary-user/other-tenant and browser/
external-network behavior, cold-cache state, filtered/paginated/CSV obligations,
full-job completion and full-page/component attribution are not established.
The approved admin scope does not waive acceptance targets or those later
validation needs. Carry them into tasks 5–8 and final verification. Task 4 is
checked only as an observation deliverable; platform recovery is not complete.
Next: task 5, local read-path/consumer attribution, starting with shared context
and remaining Coverage phases. Any further external reads need a new exact
protocol/approval; fixes, new test files, release, commit and push remain gated.

## Task 5 — Local read attribution and first frontier (2026-11-10)

Started task 5 after checking Git/checkpoint. The
[read map](PLAN-056-read-attribution.md) distinguishes committed and uncommitted
readers, shared context and all eleven measured routes. Selected route bodies
other than Home match HEAD locally; changed Home/middleware/Issues/Software
summary code must not inherit measured deployed costs. No app/test changes or
new production access.

Confirmed code findings: shared Client model roster and cached badge readers;
admin-only candidate counts; Sources' two observation aggregates have different
populations; Source Records counts/facets precede its materialized bounded page;
default Software Overview selects no title page rows but retains fleet totals;
Patching reuses posture SQL across statements and paginates formatted findings
in Python. These are code paths, not attributed timing shares. Global resource/
temp counters do not identify individual statements. Coverage retains the
separately measured lifecycle candidate, still unadopted.

Prepared the [first exact execution review](PLAN-056-source-reads-execution.md)
and collector: five Sources SELECTs, then Source Records count/types/layout/
client choices, at most nine statements on one read-only runtime-role connection
with tenant 1 and 3-second server deadlines. Stop at first failure, no page/
badge/job execution, no retry. It does not measure the wider navigation ORM
roster or fetch the Source Records row page. Source AST gates, exact selection/
default scope, in-memory success/deadline/source-mismatch/redaction/closure,
Ruff/format, registry and whitespace checks pass locally. Live compatibility is
unverified. Task 5 remains partial; next obtain approval for that exact pass,
then follow the observed component or select the next named frontier.

## Task 5 — Sources record-count frontier (2026-11-10)

User instructed next after the concrete nine-component approval request.
Executed that pass once through the shared helper with the existing runtime
role; deployed sources_status/source_records AST gates passed. Own backend
351640. At 15:48:19.419 UTC sources_health began; it completed in 0.643 s with
17 rows. sources_record_counts then hit its 3-second statement deadline:
QueryCanceled/57014, observed 3.008 s. This is not a completed query runtime.
The remaining seven SELECTs were not attempted; no skip-ahead or retry.

read_probe_finished confirmed connection closure/status 1 at 15:48:23.071 UTC.
Exit 1 was the measured SQL failure, not an inner/outer wrapper timeout.
No HTTP, auth/session, jobs, changes or other-backend cancellation. Only the
probe's own statement was canceled by its configured server deadline. Reviewed
hashes matched on both host/container copies before execution/removal; exact
files and empty directory removed, absence confirmed. Container root only
removed temporary diagnostics. No result values, raw errors or secrets emitted.
Registry/whitespace checks pass. Details:
[execution outcome](PLAN-056-source-reads-execution.md#execution-outcome--2026-11-10).

This attributes a slow component to the Sources per-instance/type record-count
SELECT, not to a specific node/function or all 10–12 s of the HTTP response.
The health read is separately observed. Companion-stream checking/grouping is
a static lead pending the actual plan. Source Records and remaining Sources
history queries are unmeasured. Task 5 remains incomplete; no fixes adopted.

Next: fresh session, verify checkpoint against Git/files, prepare a bounded
non-ANALYZE EXPLAIN of this exact SELECT with the same runtime role and source
gates, then obtain new execution approval. No next collector is prepared or
approved yet. Session rotation recommended before that independent outcome.

## Confirmed Software plan result — 2026-11-10

The corrected historical-source collector completed one non-ANALYZE EXPLAIN in 0.178 s, backend 361850, with 56 nodes and confirmed closure/cleanup. Title grouping and sorting estimates are visible; actual node costs remain unknown. See PLAN-056-home-software-plan-execution.md. Check 1 is complete; the other four checks remain authorized. Prior repeated approval requests were unnecessary.


## Remaining Home checks — bulk outcome, 2026-11-10

The user's resource-saving/bulk instruction was applied to the four remaining
checks in one invocation of `scripts/diagnostics/plan056_home_bulk.py`, SHA-256
`3e6d514f4e0ef43c0cf273139452d7bbc64e314014b66174e3aec25b82123723`.
Views and context-processor byte hashes matched committed HEAD before execution
and their deployed gates passed. One existing-role connection, tenant 1,
repeatable-read/read-only; 3 s statement, 1 s lock, 5 s idle and 60 s process
limits; stop on error. Fresh LocMem cache was confirmed without flushing.
The synthetic Home request supplied its Issues count and bypassed HTTP/auth/
session/template work. Reader availability was checked in memory; return values
were discarded. Output contained timings/error/closure only.

Backend 361991: Sources 0.332 s; Jobs 0.195 s; Home brand context cold 0.325 s;
warm 0.000 s at millisecond rounding. Status 0, connection closed. Exact
host/container hashes matched before cleanup; files and empty directory removed
and absence confirmed. No business writes, Jobs execution or HTTP calls.

All five authorized checks are complete, including the earlier Software plan.
Cold/warm here describes this fresh diagnostic process's navigation cache,
not an HTTP request or database cache. The synthetic context excludes real
session/user loading. Separate component runs cannot be summed into an exact
Home response breakdown. The major measured Home frontier remains Inventory,
Issues, Patching and Software; no remedy is selected. Full-page acceptance,
write/job contention attribution and remaining route review are still open.

## Consolidated live measurement — 2026-11-10

User explicitly requested full measurement in bulk. Reused the original
`plan056_host_observe.sh` and `plan056_db_observe.py` once: five host/database
samples over 60 s, database 19:17:54.172–19:18:54.134 UTC. Existing runtime role,
tenant 1, read-only statements with 3 s statement/1 s lock/5 s idle limits;
180 s host wrapper and original bounded database process. No workload/job was
started. Both service/source metadata and metrics were captured outside Git.

All four dashboard services were healthy. Five samples shared the same database
statistics reset epoch. Interval deltas: 153 commits, 0 rollbacks, 154 database
blocks read, 20210 buffer hits, 0 inserted/37 updated/0 deleted tuples, no temp
files/bytes and no new deadlocks. The 15 selected high-churn tables had no tuple
counter changes in this window. This is an idle baseline, not measured writer
throughput or proof of absent contention during Jobs.

Host: 62.8 GiB RAM; 30.9–30.9 GiB available (32364276–32436080 KiB).
CPU over the host sample interval: 29.14% busy excluding idle/iowait, 0.70%
iowait. Swap free 122960–124124 KiB of 8388604 KiB; page-in/out counters rose
521/409 pages. Historical swap occupancy alone does not demonstrate current
thrashing. Dashboard CPU samples: worker 0.09–0.28%, ingest 0.01–0.03%,
Operations 0.10–3.29%, Postgres 0.24–1.98% (Docker per-core percentages).
No dashboard container dominated sampled host CPU. Current RAM capacity differs
from older retained measurements; use this current sample for sizing review.

Postgres 16.14; shared_buffers 16384 8-KiB blocks (128 MiB), work_mem 4096 KiB
(4 MiB), effective_cache_size 524288 blocks (4 GiB), I/O timing disabled and
pg_stat_statements absent. Runtime role is neither superuser nor pg_monitor;
other-session state, timing and lock detail are hidden. Null activity fields
and an empty visible blocker list cannot establish absence of lock waits.

The original oldest-50 active/stalled-run sample was entirely historical stalled
rows, so a single 0.283-second read-only aggregate follow-up measured current
status totals, queue, recovery summary and completed Jobs in the last 24 hours.
It reused the database observer connection/query routine as
`plan056_current_jobs.py`, SHA-256
`7b5473d791c8b84291eec0ee261022c06fd140376cf57a65445fbb22e76ce64e`.
No running/queued jobs at that snapshot; one contained recovery claim. Historical
status totals: 23242 completed, 1093 failed, 717 stalled, 23 cancelled. Recent
scheduler/worker heartbeats were present in the first collector.

| Completed Job, previous 24 h | Runs | Mean seconds | Maximum seconds |
| --- | ---: | ---: | ---: |
| platform-evaluate | 51 | 591.463 | 986.531 |
| intel-matcher | 6 | 540.970 | 610.152 |
| resolver | 39 | 307.194 | 646.418 |
| ninja-enrichment | 24 | 291.704 | 559.469 |
| software-classify-only | 14 | 229.023 | 670.262 |
| source-refresh | 100 | 183.558 | 735.074 |
| computer-client-ownership | 195 | 19.629 | 434.847 |
| source-record-assess | 275 | 24.420 | 273.793 |

Durations are completed-run wall times, including any internal waits; overlapping
runs cannot be summed as CPU time. Failed/stalled runs are excluded from these
duration aggregates. Snapshot fields do not attribute per-job tuple writes.

Both invocations exited 0. Exact temporary host/container files were hash-checked,
removed and absence confirmed; the original host private directory was removed.
Original collector hashes: database
`8852e6534500b65f945ead6086c15a8571363dd70940c31c7aa113d72c012034`, host
`b0b5814f796c8b92d0c46a8ece8f1caef11dfa2f6c244dd7426288d295005f29`.
Raw sanitized captures are local temporary files, not repository artifacts.

Core synthesis: prioritize Home query work (Software, Issues, Inventory,
Patching) using already measured reader deadlines. The existing Software
simplification is the smallest candidate for the accepted installed-title/open-
action card; its speedup is unmeasured. Existing Issues aggregation changes need
semantic/parity review. Process-local caching only addresses repeat navigation
and does not satisfy the retained cold target. Do not select RAM tuning or
writer rewrites from this quiet sample. Coverage's previously measured lifecycle
candidate remains a separate promising slice with its documented validation gap.
For task 6, the next useful measurement is correlation during a naturally active
scheduled run; the user has authorized full read-only measurement. Avoid more
idle baselines and preserve the visibility limitation. No remedy is approved.

## Resumed platform assessment — active work and page loads

The user reaffirmed whole-platform assessment, then explicitly directed
continuing actual page-load measurement rather than stopping at an evidence
gap. No patch is selected. Git status/diffs and diagnostic sources were checked;
the existing uncommitted Home changes were preserved. In particular, the
retained Software simplification comparison (2.777/2.666 s) and process-local
caching do not demonstrate Home's retained cold-response target.

### Active-work observation

Current-Jobs snapshots at 19:33:54 and 19:36:31 UTC bracketed one normal bounded
host/database pass. Initial running keys: platform-evaluate, software-queue-drain,
source-refresh. Final snapshot: five running runs across those keys plus
source-record-assess, and one queued intel-matcher. No job was started manually.
The final aggregate failed-run total rose by one; no failure cause was read and
this does not identify which run failed.

The collector completed its five-sample window and exited 0. The first tool
response was truncated before capture; only samples 1–4 are retained completely.
Do not reconstruct a 60-second delta. Across the retained 44.984-second database
interval, 19:34:25.669–19:35:10.653 UTC, observed counter differences were:

| Counter/table | Observed change |
| --- | ---: |
| Database commits / rollbacks | +289 / 0 |
| Database inserts / updates / deletes | +81 / +21,698 / +46 |
| Database blocks read / buffer hits | +210,042 / +1,194,779 |
| Temp files / bytes / deadlocks | 0 / 0 / 0 |
| Relationship current updates | +9,994 |
| Relationship history updates | +4,997 |
| Condition assessment inserts / updates | +5 / +484 |
| Finding-state inserts / updates | +5 / +495 |
| Finding inserts / updates | +5 / +484 |

All selected table counters were monotonic in the retained samples. Database
`stats_reset` was null throughout, so a reset epoch cannot be certified. These
are observed differences, not reset-certified per-job rates. Unchanged selected
tables do not establish no work elsewhere; buffered/in-progress work and
statistics lag remain possible. Database block reads are not physical disk I/O.

Retained host samples at 19:34:24–19:35:09 UTC show 35.04% CPU busy excluding
idle/iowait, 1.21% iowait, and 30.58–30.78 GiB available RAM. Swap page-ins rose
424 pages; page-outs were unchanged. This interval establishes active writes
alongside scheduled work, not a particular job's write cost or the cause of slow
pages. Runtime-role lock/session visibility remains restricted. No extension,
role, configuration or instrumentation changed.

All three reviewed host files and both container copies matched their original
SHA-256 values before cleanup. Exact files and the empty private directory were
removed and absence confirmed. The [resumed protocol](PLAN-056-measurement-protocol.md#resumed-full-page-measurement)
owns the following HTTP pass; it captures complete redacted output before
summarizing to avoid the earlier truncation limitation.

### Full-page results

One normal configured-admin login, sequential requests and confirmed normal
logout. The 25 attempted page requests ran 19:37:30–19:42:10 UTC on internal
loopback port 3002; 24 returned HTTP 200 with complete HTML bodies. The final
Coverage request hit its 120-second client deadline. Its repeat was not sent.

| Page/variant | First complete HTML time | Immediate repeat |
| --- | ---: | ---: |
| Settings | 2.779 s | 0.211 s |
| Home | 15.908 s | 9.433 s |
| Clients | 4.346 s | 5.705 s |
| Computers | 1.802 s | 1.485 s |
| Issues | 5.629 s | 2.866 s |
| Sources | 8.599 s | 9.212 s |
| Source Records | 9.765 s | 8.929 s |
| Software | 12.196 s | 15.674 s |
| Patching | 9.647 s | 10.499 s |
| Jobs, refresh off | 1.743 s | 1.281 s |
| Computers, page 2 | 2.824 s | 1.392 s |
| Source Records, page 2 | 7.772 s | 10.260 s |
| Coverage Computers | Incomplete at 120.000 s | Not attempted |

For completed requests the maximum header-to-body interval was 0.005 s. The
dominant measured delay precedes HTML delivery on this internal path. This is
not browser rendering, asset loading, external-network or ordinary-user timing.
Worker/cache state was not controlled; first/repeat cannot be labeled cold/hit.
Changes in bytes for some pages are not a content-parity check. Different
concurrent work prevents comparisons with older samples being called speedups
or regressions. No Home target is waived or met by these results.

Two bounded completion-log checks found all 24 successful markers/statuses,
and neither found the exact Coverage marker. The final check was more than
70 seconds after the first. Coverage started at 19:40:10.684 UTC; the client
stopped waiting at 19:42:10.684. This is an observed page-load failure, not a
completed 120-second response. Its server-side work may survive disconnect;
completion remains unconfirmed. No duplicate request, cancellation or restart.

The overlapping 20-sample host observation reported 40.10% CPU busy excluding
idle/iowait, 1.39% iowait, and 30.40–30.64 GiB available RAM. Whole-database
counter differences between before request 1 and after request 25 were
+7,625,620 blocks read, +22,601,433 buffer hits, +80 temp files/
+1,070,858,998 temp bytes, +18,868 inserts, +103,986 updates, +15,575 deletes
and zero new deadlocks. `stats_reset` was null at both ends, so these remain
observed differences without a certified reset epoch. Counters include all
concurrent work and cannot be assigned to individual requests or Jobs.

Snapshots showed source-refresh and intel-matcher running across the page pass;
platform-evaluate, resolver and ownership work overlapped parts of it. Queued
work reported capacity/dependency waits. These are Jobs admission states, not
PostgreSQL lock-wait attribution. Temp bytes also rose during Coverage's wait,
but no statement-level evidence assigns them to Coverage. No whole-host CPU/RAM
exhaustion is demonstrated by this window; database/cache/I/O and lock effects
are not excluded.

HTTP collector and host wrapper exited 1 because of the measured Coverage
timeout, not a collector-wrapper timeout. Logout was confirmed. All four stack
services were running/healthy at follow-up. Five host and three container
diagnostic copies matched reviewed hashes before exact cleanup; the completion
sentinel and empty private directory were removed and absence verified. This
does not claim that Coverage's application work ended.

Collector hashes: matrix `5b00feaed17a8371f9c3a2dc2f9eb5e2cc237d82b6ae20a5e52c93b6b9ebcfa3`,
authentication helper `626fc08b9ed3443d8cb01b967d57d5d3d86218b3704051e0c55d6f71a0c8b045`,
completion filter `7f8284801e484755bef20d427901802edaf48fd5188999d89c7e8e4d11921db9`.
Database/host helper hashes are retained in the earlier execution records.
Complete redacted HTTP/resource capture remains outside Git. Python AST,
targeted Ruff check/format, completion-filter shell syntax, registry validation
and whitespace checks pass. No runtime/test files, dependencies, schema or
release metadata were changed during this resumption.

### Cross-service interpretation and assessment boundary

The evidence now connects widespread slow page responses with an active
database workload; it does not establish one universal cause. Keep these
questions separate while developing the platform recovery design:

| Concern | Established | Still needed to choose a platform remedy |
| --- | --- | --- |
| Read amplification | Multiple full pages remain slow on repeats; shared navigation and source-metadata consumers are mapped. Coverage has a measured query-shape candidate. | Cost shares and semantic contracts for shared reads; Coverage's remaining page work and completion. |
| Write amplification | Relationship current/history counters rose during natural work; code inventory identifies replacement and freshness writes elsewhere. | Distinguish required evidence/freshness from unchanged content; bounded per-job contribution and refresh cost. |
| Scheduling and contention | Reads overlapped dependent Jobs; capacity/dependency admission waits were visible. | Actual database waits and transaction cost; Jobs queue categories cannot substitute for them. |
| Capacity | Significant buffer-read/temp activity coexists with available host RAM and CPU headroom. | Statement-level spill/cache/physical-I/O attribution before sizing or configuration changes. |
| Retention | Activity retention and rollup consumers remain within transferred scope. | Current age/size and refresh cost, then an explicit retention/payload decision. |

No Software-only patch, cache rollout, index, writer rewrite, typed-fact schema,
memory increase or retention rule is selected. The next assessment step is to
resolve outstanding page completion/access variants and connect the measured
read/write boundaries to alternative platform designs with explicit freshness,
security, recovery and write-cost tradeoffs. Ordinary-role, tenant/filter, browser
and controlled-cold verification remain open. This page pass supplies actual
load outcomes; it does not close PLAN-056 or claim complete platform attribution.

## Coverage state check — outstanding item 1

User explicitly requested completing item 1 after its read-only scope was
explained: establish the exact request's completion and any surviving database
work; no page replay, cancellation or other measurement. Reconciled Git status,
handoff and reviewed prior diagnostics. Prepared `plan056_coverage_state.sh`
and `.sql` for the current request marker ending `_25`, starting
2026-11-10 19:40:10.684508 UTC; the historical `_9` diagnostic is not reused.

One helper-mediated invocation on am-ch-01: service start/health metadata, at
most 10,000 Operations log lines since 19:40 UTC filtered to the exact marker,
then one current-database activity snapshot via the documented existing
`docker exec ninja-postgres psql -U ninja -d ninja` inspection connection. This
identity is needed because runtime-role session visibility is restricted.
No grants, role changes, query text, business tables or customer data. Snapshot
counts all active/Coverage-shaped/idle-transaction sessions and returns at most
50 active/idle-transaction metadata rows across application names, avoiding the
old diagnostic's restrictive `application_name='operations'` filter. Query-shape
similarity does not identify the HTTP owner. Normal idle sessions' historical
last statements are not treated as running work.

Wrapper bounds: 30 s overall, 10 s logs, 12 s psql; SQL connection/transaction
read-only with 3/1/5 s statement/lock/idle deadlines. Fresh private
`/tmp/plan056-coverage-state.XXXXXX` directory, only two reviewed files, SHA-256
verification before invocation and exact cleanup afterward. No remote Python.
Local shell syntax, registry and whitespace checks pass; execution pending.

Executed once, exit 0. At 19:57:45.605 UTC, full statistics visibility confirmed
(inspection identity superuser/read-all-stats; database matched). Snapshot found
two active database sessions, one Coverage-shaped, and zero idle transactions.
The Coverage-shaped backend was PID 363232: backend start 19:40:10.695865,
transaction start 19:40:10.722880, query start 19:40:11.907387 UTC; query age
1,053.698 s (17 min 33.7 s). Its connection and transaction began approximately
11 ms and 38 ms after the timed Coverage request. No blockers and no wait event
were reported for it at this instant; this does not prove uninterrupted CPU use
or absence of earlier waits. The other active session was not Coverage-shaped.

The bounded log read returned only 39 lines, below the tail cap, with no exact
Coverage completion marker. Operations/Postgres remained healthy, with start
timestamps before the request. No service restart explains away this work.

**Item 1 observation is complete: surviving Coverage-shaped database work was
found; the request must not be treated as finished or replayed.** Timing and
query shape strongly associate this backend with the timed request, but its HTTP
marker was not propagated to SQL, so exact HTTP-to-backend ownership remains an
inference. No successful completion or final HTTP outcome is established.
No cancellation, page replay, business read/write or other measurement occurred.

Both host files matched reviewed SHA-256 values before invocation and cleanup;
exact files and empty private directory removed and absence confirmed. Shell
hash `de35eba2d20d0d6477fecedbbdd9d35cc81693a6158a91117e66d2cb674a9250`;
SQL hash `e3272085c0554172ddc1430b194b824c90d67ca666ab3f87f5f8b029db0b9e92`.
Do not cancel this or any other backend without separate explicit authorization.

## Authorized cancellation and Coverage retry

User explicitly instructed: cancel, then retry and use the retry for measurement.
Scope: cancel only the identified original Coverage statement if its PID,
backend-start, transaction-start, query-start, shape and current query fingerprint
still match; verify its transaction closes before one normal configured-admin
Coverage GET. A changed identity fails closed. No termination or restart.

Reviewed `scripts/diagnostics/plan056_coverage_retry.py`: host mode runs catalog
SQL directly through the documented inspection connection; HTTP mode inside
Operations reuses the normal-login helper without exposing/transferring mounted
credentials. Catalog snapshots every 15 s return current statement fingerprints,
timings/waits/blocker counts and database counters, never SQL/customer content.
The matching retry backend must be the sole Coverage-shaped leader with a
transaction beginning after the HTTP request; subsequent samples pin that
backend/transaction. Per-process CPU/I/O counters come from its container `/proc`
files; host CPU/available-memory counters are passive. Parallel-worker CPU is
not included in the leader's counters. No extension or configuration change.

Retry observation limit 120 s, HTTP safety deadline 150 s, host loop 240 s,
outer wrapper 300 s. SQL timeout 3 s, lock 1 s, idle 5 s; subprocess SQL 10 s,
process counters 5 s. At the observation limit, cancel only the identified retry
Hudu statement with fresh exact identity/fingerprint guards; no other work.
Verify transaction closure and normal logout. Ambiguous attribution stops the
collector; no fallback to broad cancellation. Failed-page timing is a measured
failure, not a successful load or evidence that the query would finish at 120 s.

Fresh `/tmp/plan056-coverage-retry.XXXXXX` host directory, two reviewed Python
files, exact absent-path checks/copy to Operations, SHA-256 verification before
execution and cleanup. Native host Python invokes reviewed files by path only;
SQL input goes directly to psql. No tests, dependencies or runtime files changed.
Capture all redacted output locally; record actual cancellation/retry outcomes
and limitations before completing this slice.

### Cancellation and retry outcome

Executed once on 2026-11-10; host collector exited 0. Original PID 363232 still
matched all pinned timestamps, statement shape and fresh fingerprint. Guarded
`pg_cancel_backend` returned true at 20:13:19.085 UTC, after 1,987.178 s
(33 min 7.2 s) of that statement's execution. At 20:13:20.304 the original
transaction had closed and the full-visibility active/idle-transaction snapshot
was empty. No backend termination, service restart or unrelated cancellation.

One normal configured-admin Coverage GET began at 20:13:22.215 UTC with marker
`069a6f0b88fde810bb2ebb1a4600a0ca_1`. New backend PID 365157 began at
20:13:22.231251, transaction at 20:13:22.262625; its Hudu/lifecycle SELECT began
at 20:13:23.480062. It was the sole matching Coverage leader with a transaction
beginning after the request, and the same backend/transaction remained pinned.

Eight Hudu samples from request elapsed 15.537 through 120.229 s retained the
same statement fingerprint `794fae6b29a3bba65f3060e502061007`, zero blockers and
no reported wait event. No parallel workers were observed. Initial sample at
0.286 s was an earlier statement; two final samples followed cancellation.
These snapshots do not prove absence of waits between samples or identify an
internal plan node's cost.

Automatic process-counter collection could not read the PostgreSQL process's
I/O file under the default container user. A bounded corrective read under the
existing `postgres` service user succeeded during this same retry: at
20:15:09 UTC, backend CPU was 10,662 ticks at 100 ticks/s (106.62 CPU seconds),
process start was 400,620.59 uptime seconds, and sampled uptime 400,727.97.
That is 107.38 s of process lifetime and approximately 99.3% of one CPU core.
Counters cover the new backend's lifetime, including early request setup, not
only the Hudu statement. Physical process I/O counters were 827,392 bytes read
and 2,269,184 bytes written. A second corrective sample 15 s later found the
process already gone after the planned cancellation; no two-point process I/O
rate or complete process trace is claimed. The query's CPU/I/O split is not
inferred from whole-database buffer counters.

At the measurement limit, a fresh exact PID/backend/transaction/query-start/
fingerprint/shape guard matched only retry PID 365157. Cancellation returned
true at 20:15:22.872 UTC. The client received HTTP 500 at 20:15:22.946,
elapsed/header time 120.730 s, 145 response bytes, contents discarded. **This
500 was induced by the authorized measurement-limit cancellation; 120.730 s
is neither a successful page-load time nor an uncanceled failure time.**
No immediate repeat or third request was made. Normal logout was confirmed.

At 20:15:23.907 UTC the retry transaction was closed and the full-visibility
active/idle-transaction snapshot was empty. There is no surviving statement or
transaction from either diagnostic at this verified endpoint. All four stack
services were running/healthy at follow-up.

Baseline-to-final observed database differences: +152,128 blocks read,
+9,474,387 buffer hits, +4 inserts/+93 updates/+4 deletes, no new temp files/
bytes or deadlocks. `stats_reset` remained null; no certified reset epoch or
per-query attribution of these global counters is claimed. Host samples show
30.60% CPU busy excluding idle/iowait and 1.16% iowait. Other database work
appeared in some samples, including an autovacuum; the above counters include it.

Interpretation: the retry reproduces a CPU-heavy Coverage request held in the
Hudu/lifecycle SELECT, with no sampled lock blocking and little physical I/O
reported by its backend. This is stronger attribution than the earlier client
timeout. It does not identify the expensive internal plan node, validate the
candidate rewrite, establish a successful full-page time or finish the platform
assessment. No runtime fix or infrastructure remedy is selected.

Two host and two container diagnostic files matched reviewed hashes before
execution and cleanup; exact copies/empty host directory removed and absence
verified. Collector SHA-256
`eaaff3a4d34b394dda263518c1ef7644355e45b3ce9a4c3a7e6f3ac30ab6de39`;
authentication helper `626fc08b9ed3443d8cb01b967d57d5d3d86218b3704051e0c55d6f71a0c8b045`.
Complete redacted captures remain outside Git. Python syntax, targeted Ruff
check/format, registry and whitespace checks pass. No runtime/test files,
dependencies, schema, persistent settings, release metadata or Git history changed.

## Coverage internal-work diagnosis

User requested digging into the reproduced bottleneck. This is diagnosis only,
not candidate adoption or an application/schema fix. Existing full read-only
measurement authorization applies to one bounded runtime-role probe.

Reviewed `plan056_coverage_deep.py` with the existing candidate/component helpers:
verify deployed Coverage/current-Computer ASTs, tenant 1, one repeatable-read,
read-only snapshot, five-second per-statement/one-second lock/five-second idle
limits. Up to nine diagnostic SELECT/EXPLAIN statements: catalog metadata/view
definition fingerprints, three eligible observation IDs retained only in memory,
actual original plans restricted to one and three IDs, actual full candidate
and materialized-reference plans, and two full result reads compared as multisets.
No full-original execution, HTTP, Jobs, cancellation, settings or data changes.

Reference query computes the same existing security-barrier lifecycle view once
in a MATERIALIZED CTE, retaining all tenant/observation/lifecycle rows and the
original left-join predicates/projections without LIMIT or DISTINCT. Candidate
is the previously reviewed correlated lookup. Both retain the authoritative
editable policy, views and app-role security. Equality against this reference
is broader evidence than prior three-record parity; it is not a full-original
timing or exhaustive future-policy/security acceptance test.

EXPLAIN ANALYZE output is allowlisted numeric counters and schema object names;
no SQL expressions, row values, identifiers, view definitions or credentials.
Node rows/times are per-loop values; use loops when interpreting repeated work,
and do not sum inclusive parent/child timing. See
[PostgreSQL EXPLAIN](https://www.postgresql.org/docs/16/sql-explain.html) and
[planner statistics/security](https://www.postgresql.org/docs/16/planner-stats-security.html).
Original sample timeouts roll back only their savepoint, preserving the snapshot
for independent candidate/reference checks; other errors or parity mismatch stop.
Own server deadlines bound all reads; no external backend cancellation.

Fresh private `/tmp/plan056-coverage-deep.XXXXXX`, three exact reviewed files,
absent-path checks and SHA-256 verification before container execution/cleanup.
Outer wrapper 90 s, inner diagnostic process 75 s plus 5 s termination grace;
capture complete redacted output locally. Syntax/Ruff/format/registry/whitespace
checks precede execution. No runtime/test files or dependencies are changed.

First probe exited 1 with confirmed connection closure: original one/three-ID
actual plans and full candidate plan completed; the MATERIALIZED lifecycle-only
reference hit its own five-second deadline. No full result comparison ran.
Actual nodes show 43,838 lifecycle rows per original outer record and mapping
scan loops 43,838/131,514 for one/three IDs. Full candidate returned 4,870 rows
with 4,870 primary-key/lifecycle lookups in 512.242 ms. These are actual plan
observations; interpretation/results are recorded after completion below.

Bounded follow-up `plan056_coverage_reference.py` avoids asking the SQL planner
to join the reference: read the original Hudu/Computer/ownership population and
the complete existing lifecycle view independently, then perform the original
tenant/observation left join in memory. Preserve duplicate right matches,
unmatched/null semantics and all six projected fields; no deduplication or
normalization. Compare the complete multiset against one full candidate read
in that same runtime-role repeatable read-only snapshot. Three SELECTs plus
transaction setup, five-second statement limits, 100,000-row input/output bounds.
All row values remain in process memory and are discarded, never emitted/saved.
Reuse this task's verified three helpers without overwriting; transfer/hash-check
only the new fourth file to absent paths, invoke by path with 75/90 s bounds,
then hash-check/clean all four host/container copies together. No rerun of the
completed actual plans or full-original execution. No HTTP, changes or new tests.

### Confirmed mechanism and full reference result

Source gates passed on both diagnostic runs. The first runtime backend was
366940 at 20:48:13 UTC; actual plans completed for original one/three IDs and
the full candidate. The reference SQL timeout was server-enforced and connection
closure confirmed (exit 1); no surviving work was left or canceled externally.
The follow-up backend 367158 completed at 20:51:16 UTC, exit 0, connection closed.

| Variant | Actual output rows | Lifecycle branch rows per loop | Lifecycle branch loops | Policy-lookup loops | Server execution |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original, one eligible Hudu observation | 1 | 43,838 | 1 | 43,838 | 582.037 ms |
| Original, three eligible Hudu observations | 3 | 43,838 | 3 | 131,514 | 2,582.817 ms |
| Full correlated candidate | 4,870 | 1 | 4,870 | 4,870 | 512.242 ms |

The original top left nested loop discarded 43,837 join candidates for one
requested record and 131,511 for three. Its lifecycle subtree computes the
tenant's broad observation set, including source-instance/source joins and
ordered JSON lifecycle-policy matching, before the outer observation-ID join
rejects almost every row. It is recomputed per Hudu row in these actual plans.
For the one-record sample, the outer Hudu/ownership/device work completed in
0.332 ms, versus 573.952 ms inclusive for the lifecycle subtree. In the
three-record sample the subtree averaged 848.278 ms across three executions.
Inclusive node timings must not be summed down the plan tree.

The candidate instead performs an `entity_observation_current_pkey` lookup
returning one observation per Hudu row, followed by that observation's existing
lifecycle policy. The index already exists and is usable. Full candidate outer
Hudu/ownership/device work produced 4,870 rows in 187.286 ms; lifecycle lookup
averaged 0.065 ms per row. These are instrumented node observations in this
window, not guaranteed latency or a successful page-response measurement.

The unrestricted candidate's outer relation was estimated at **one row** but
actually produced **4,870**. Earlier joins estimated 12 ownership matches versus
4,935 actual, from 5,988 actual Hudu view rows. This severe underestimation helps
explain why the planner accepts the broad nested-loop access path. Stale
statistics are not established as the cause. Both installed views retain
security barriers/current-tenant predicates; the lifecycle view retains its
lateral mapping lookup. UUID equality is leakproof, tenant lookup STABLE, and
the application role lacks direct observation-table SELECT. Do not attribute
the issue to a non-leakproof UUID equality or remove the security boundary.

If the same broad-per-record work scales to 4,870 outer rows, it implies about
213,491,060 lifecycle-policy lookups (43,838 × 4,870). That is a **projection
from the sampled plan**, not a completed full-original execution count or
uncanceled run-time estimate. It is consistent with the separately observed
CPU-heavy, many-minute Coverage statement. The original full query was not
replayed for this diagnosis.

Full-reference follow-up, one read-only repeatable snapshot:

- Original Hudu/Computer/ownership population, without the lifecycle join:
  4,870 rows, 0.272 s fetch-inclusive.
- Full authoritative lifecycle view: 43,838 rows, 0.981 s fetch-inclusive.
- In-memory tenant/observation bag left join: 4,870 rows, 0.223 s.
- Full correlated candidate read: 4,870 rows, 0.641 s fetch-inclusive.
- All six projected fields and row multiplicities matched exactly as multisets.
  Null keys/unmatched states and duplicate right matches are preserved by the
  reference algorithm. No business values, IDs or payloads were emitted/saved.

This checks the complete current tenant result against an independent execution
of the existing view/join semantics. It does not replace future-policy fixtures,
other-role/tenant validation or actual full-page verification. Ordered samples,
different plans and warmed data prevent a universal speedup ratio. The simple
MATERIALIZED lifecycle-only SQL reference itself exceeded five seconds; it is
not a demonstrated remedy. Its failed plan did not provide actual node counters.

### Cross-service scope and next decision

Static consumer tracing found the same lifecycle view in Coverage's later source
totals, `_device_source_records`, identity findings/matching, evaluator presence
checks and Computer listing. `_device_source_records` and identity name readers
also use ordinary lifecycle joins; evaluator uses correlated EXISTS and listing
has its own grouped join. Their plans/roles/populations differ, so sharing the
view does **not** establish the same measured defect. Carry this confirmed
read-amplification mechanism into the remaining platform attribution rather than
changing the shared view or every caller without evidence.

The narrow candidate direction is to scope the lifecycle lookup to the current
observation before evaluating its policy, preserving the same authoritative
view, tenant predicates, ownership and projected data. It is not adopted or
implemented. Root-plan acceptance, cold/full-page behavior and the unmeasured
frontiers remain open; no performance target is waived.

Four host/four container files matched hashes before execution and exact
cleanup; empty private directory removed and absence verified. Deep collector
SHA-256 `b29a556de2abce4b378ac237ea5392df10481e55c51ef317ba004e3a8841639b`;
reference collector `9aea6c8bb80a78159c163e05019ff0eeaa2eb26c8495e941bcdcf0757096d262`.
Candidate/component helper hashes are unchanged from their earlier reviewed
records. Full redacted plan/reference captures remain outside Git. Syntax,
focused Ruff/format, registry, blueprint-size and whitespace checks pass.
No application, schema, policy, permissions, tests, dependencies, release,
commit or deployment changes occurred.

## Outstanding item 2 — deferred until after Coverage fix

User decision: additional timing of unchanged Coverage is irrelevant to the
current assessment because its bottleneck is confirmed. The long-run proposal
below is withdrawn; no long request was launched and no approval is pending.
Retain the known failure, actual-loop diagnosis and full current-data parity
as sufficient assessment evidence for this frontier. Coverage is the first
confirmed high-priority fix candidate for later implementation review; no
application fix or deployment is approved by this decision. Completed default
page/first-repeat measurements remain post-fix validation, not a passed or waived
requirement. Continue other assessment items, with ordinary-user timings next.
Existing authorized non-admin access remains unidentified. Current checkpoint
has been saved for a recommended fresh session before the next measurement.

User selected item 2: obtain a completed default Coverage response and immediate
repeat. The deployed query is unchanged; prior requests exceeded 120 s and the
original statement was canceled after 1,987 s, with sampled actual plans showing
43,838 lifecycle computations per Hudu row. A successful request may take tens
of minutes. The existing matrix protocol caps each pass at 15 minutes, so no
new long request has been launched under that budget and no candidate-query
time is relabeled as deployed page latency.

Concrete proposed extension for the user's choice: one configured-admin normal
login, one default Coverage GET up to 75 minutes, one immediate repeat only after
the first full HTTP 200 response, normal logout. Maximum two sequential GETs and
150 minutes page wait plus setup/cleanup. Passive metadata samples at most once
per minute. Begin only after confirming no surviving Coverage work. Record UTC,
header/full-body timings, status, byte counts and concurrent workload; discard
bodies. If a request exceeds its budget, cancel only its uniquely attributed,
timestamp/fingerprint-pinned current statement, verify transaction closure, and
do not repeat. No backend termination, restart, schema/config/data changes,
application fix or synthetic substitute. Exact temporary script/hash/cleanup
review would have preceded execution if selected. This proposal was never
authorized/executed and is superseded by the user's deferral above.

## Outstanding item 3 — non-admin account unavailable

User requested item 3, ordinary-user timings. Rechecked the handoff, Git state,
prior access review and available helper-profile capabilities without exposing
private values. Profiles provide SSH, Portainer and source-service access; no
ordinary-user Operations profile or browser session connector was identified.
The prior measurement login uses the mounted configured-admin credential.
Static review found login-required paths for Home, Clients, Computers, Issues,
Sources, Source Records, Software and Patching; known-expensive Coverage remains
deferred and staff pages are excluded from an ordinary-user matrix.

Asked for an existing authorized non-admin account/session or secure reference.
The user explicitly confirmed **no non-admin account exists**. Therefore this
measurement is not applicable to the current deployment, rather than a passed
ordinary-user timing check. No user enumeration, role changes, new account,
impersonation, synthetic session, authentication or remote request was performed
for this item. Existing admin timings cannot establish ordinary-user performance.
Revisit if such an account is introduced. Next numbered measurement is item 4,
controlled cold navigation; the checkpoint is saved for a recommended fresh
session before that independent measurement.
