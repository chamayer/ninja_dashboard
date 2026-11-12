# PLAN-056 — Consolidation and transferred scope

Consolidated 2026-11-09 at the user's request. PLAN-056 is the sole execution
authority for this performance work, including later approved implementation
and verification. The eight predecessors are superseded, not completed.
Their documents retain detailed evidence, recovery notes and settled decisions;
their implementation proposals and approval claims are historical, not automatic
instructions to ship. Completed releases are not reversed by consolidation.

## Transferred work and acceptance obligations

| Predecessor | Scope now owned by PLAN-056 | Resume evidence and constraints |
| --- | --- | --- |
| PLAN-041 | Host CPU attribution, matcher CPE reuse and CVE batching; completed DMARC work remains historical | Verify actual deployed matcher code and whole-run results; preserve membership, version filtering and withdrawals. Never run a full matcher locally. |
| PLAN-044 | All-page/navigation performance, Home summaries, Coverage pagination/filter/CSV semantics, Inventory trends, Patching and Software readers | Preserve current worktree. Last recorded Home 9.090 s; prior ordinary Home target ≤1.5 s, hard maximum under 2 s including cold navigation, and accepted ≤60 s summary age remain review inputs, not waived. Preserve tenant/client scoping, independent actions, domain ownership, supported trends and complete filtered CSV. |
| PLAN-047 | Projector/evaluator write churn, per-run timestamps, full refreshes, storage growth and possible compaction | Inventory writers/readers and real changes versus timestamp-only writes; preserve freshness meaning. Re-measure before any separately authorized compaction. |
| PLAN-048 | JSON/TOAST costs in Source Records and shared metadata readers | Typed-fact design and proposed ADR-0055 need review, not automatic adoption. Preserve all view fields, withdrawn/unlinked records, security barrier and RLS; rehearse migration locking. |
| PLAN-049 | Active-finding access for the /devices/ page | Candidate commit 4cb502e0 and absent old worktree require verification. Old migration 0404 conflicts; rebase and assign a valid number after current migrations only if adopted. Not the separate Coverage route. |
| PLAN-050 | Database memory and shared host capacity | Refresh historical settings and memory/I/O evidence; distinguish swap occupancy from active swapping. No blind memory increase; host changes/restart need approval. |
| PLAN-053 | Activity retention, raw payload volume and rollup refresh cost | Verify readers and refresh definitions; retention period requires a user decision. Deletes, payload trimming and physical rewrites each retain separate gates. |
| PLAN-054 | Source/software lock coordination, collection recovery, guard waits and deadlock stability | ADR-0056 and deployed repairs remain in force. Verify current code and scheduled-run stability; contradictory old release checkpoints require reconciliation, not replay. |

Tasks 1–6 inventory and measure all these workstreams; tasks 7–9 decide an ordered
design; tasks 10–12 implement, release and verify approved slices within PLAN-056.
No predecessor is resumed as a parallel plan. Deferred or rejected proposals get
an explicit disposition here or in the repository backlog, not silent deletion.

## Related work outside supersession

Completed correctness plans (including PLAN-045/055), entity/identity/security
contracts and unrelated feature plans retain their status. PLAN-042 is referenced
as historical measurement evidence, not an independent active plan; its linked
record was absent in this checkout and must be located or marked unavailable in
task 1. PLAN-051 obsolete writers and PLAN-019 retention follow-ups are dependency
inputs to inventory; they are not automatically authorized or absorbed wholesale.
Expand consolidation if task 1 finds additional standalone performance scope.

## Preserved Operations checkpoint

This is the pre-consolidation handoff, not a current-state assertion.

## PLAN-044 — Navigation and Computers performance

**Goal:** Ordinary Home ≤1.5 seconds; hard maximum under 2 seconds. Preserve
the agreed domain KPIs, supported trends, known-client impact counts, and
Clients portfolio boundary. The user revised the Software card to installed
titles and open Software & Security actions; detailed decisions remain on Software.
**Scope/files:** Home/Issues/navigation readers and template, source-record
finding publication, Patching, Software, and Inventory owner readers. Exact
files, ordered steps, decisions, and acceptance checks are in the
[current implementation plan](../../operations/docs/plans/PLAN-044-page-performance.md#home-implementation-plan--2026-11-09-review).
**Checkpoint:** The last recorded complete Home request took 9.090 seconds.
Home now caches four summaries per process for at most 60 seconds. The revised
Software card and title reader are implemented; 20 focused Python 3.12 checks
and 13 Issues PostgreSQL checks pass. Production comparisons matched: Issues
4.045→1.556 seconds; Software title count 2.777→2.666 seconds in single ordered
samples. Full Home latency remains unmeasured. The local dev database is at
migration 0391. The [plan](../../operations/docs/plans/PLAN-044-page-performance.md#summary-design-exploration-set-aside)
retains validation, evidence and the release metadata gap. **Next:** Hold
implementation while [PLAN-056](../plans/PLAN-056-platform-performance-assessment.md)
assesses platform-wide performance. Preserve current changes; the proposed
title-count table remains unapproved. No new schema has been implemented.

## Preserved predecessor registry checkpoints

Historical gates and deployment claims below require reconciliation in task 1.

## PLAN-041 — Host CPU and runtime profiling

- Scope: Attribute live host CPU, replace expensive DMARC health checks in its sibling repository, and reduce Ninja matcher work through bounded candidate reuse and indexed CVE lookup batches.
- Status: active
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: —
- Blueprint: docs/plans/PLAN-041-host-cpu-and-runtime-profiling.md
- Source: docs/plans/PLAN-041-host-cpu-and-runtime-profiling.md
- Section: PLAN-041 — Host CPU and runtime profiling
- Related plans: PLAN-003/004 own findings guards and identity semantics; this plan adds diagnostics only and does not alter their contracts. DMARC health/monitoring retirement is prepared in the sibling repository.
- Resume gate: Existing CPU-task implementation/commit/push authorization continues after the user's request to finish the fix. Release 0.142.2 has no migrations or dependencies; preserve matching scope and withdrawals. No host tuning, systemd parser units, or Zabbix parser monitor.
- Last checked: 2026-11-02 (0.142.1 and DMARC `03ddf01` deployed and healthy. Actual matcher fixes prepared: bounded CPE reuse and 500-CPE CVE batches; live read-only equivalence/performance probes passed; whole matcher-run validation follows deployment).

## PLAN-044 — Navigation and Computers performance

- Scope: Achieve ordinary Home response time ≤1.5 seconds (2.0-second hard maximum), preserving the agreed domain-owned Operations overview, supported trends of 30 days or less, current Coverage totals without a separate Home trend, and detailed client portfolio on Clients. The user accepted Home summary values up to 60 seconds old and revised the Software card to installed titles plus open Software & Security actions.
- Status: active
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-044-page-performance.md
- Section: PLAN-044 — Navigation and Computers performance
- Related plans: PLAN-042 supplies prior performance evidence; PLAN-012 retains Computer semantics and verification; PLAN-043 independently owns issue review in views.py. PLAN-019 source-record history is complete. PLAN-003/004 contracts remain unchanged. PLAN-049 follows this plan's migration 0406 and must use 0407 or later.
- Resume gate: Commit and push require separate approvals; an origin push approval must include automatic deployment and reviewed pending migrations. A cache-miss latency tradeoff question is pending.
- Last checked: 2026-11-09 (`ca00938a` and SQL 119 are recorded as deployed; Home returned 200 in 9.090 seconds. Approved same-snapshot comparisons matched: Issues 4.045→1.556 seconds; simplified Software title count 2.777→2.666 seconds in single ordered samples. Full Home latency remains unmeasured. PLAN-049 remains separate at 0407+).

## PLAN-047 — Write only what changed

- Scope: Make projectors, evaluators and refreshes write only changed rows; move per-run timestamps off content rows; replace always-changing materialized views; compact tables only after re-measurement.
- Status: ready
- Defined: 2026-11-03
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-047-write-only-what-changed.md
- Source: docs/plans/PLAN-047-write-only-what-changed.md
- Section: PLAN-047 — Write only what changed
- Related plans: Found by PLAN-012's follow-up review. PLAN-041 owns prior matcher CPU fixes; PLAN-014 owns requirement verdict policy; PLAN-019 owns pipeline correctness and retention. Work in a separate worktree while PLAN-045 is in progress in the main checkout.
- Resume gate: Step 1, a local code inventory of each writer, needs no external access; migrations, rehearsal, release and any compaction are separately gated.
- Last checked: 2026-11-03 (read-only counters over about 13 days: cve_match 74 M inserts and deletes for 649 k rows; relationship evidence 27 M updates for 118 k rows; device_requirement_state fully deleted and re-inserted per evaluation).

## PLAN-048 — Source records report typed facts, not JSON parsed on read

- Scope: Derive a source record's reported facts as typed columns when it is written (ADR-0055) so that v_entity_observation_admin_metadata and its six readers never parse the record JSON on read.
- Status: ready
- Defined: 2026-11-03
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-048-record-reported-facts.md
- Source: docs/plans/PLAN-048-record-reported-facts.md
- Section: PLAN-048 — Source records report typed facts, not JSON parsed on read
- Related plans: Found by PLAN-012's follow-up review (Source Records about 8 s). PLAN-047 owns write volume and observation storage; PLAN-004 owns reported contact semantics. Work in a separate worktree while PLAN-045 is in progress in the main checkout.
- Resume gate: Step 1 (measure the migration lock on a production-size copy and the expressions read-only on production) needs rehearsal approval; ADR-0055 must be accepted before the migration.
- Last checked: 2026-11-03 (JSON read costs 3 to 4 s per full view scan regardless of extraction style; claims cover 9 of 15 fields and no withdrawn records).

## PLAN-049 — Index active findings by subject

- Scope: Partial index on active findings by subject (migration 0404) and a page-id probe in the /devices/ Computers page so severe-Issue counts read only active findings.
- Status: active
- Defined: 2026-11-03
- Started: 2026-11-03
- Completed: —
- Blueprint: docs/plans/PLAN-049-active-findings-index.md
- Source: docs/plans/PLAN-049-active-findings-index.md
- Section: PLAN-049 — Index active findings by subject
- Related plans: Found by PLAN-012's follow-up review. PLAN-042/PLAN-044 own the Coverage-view (/inventory/computers/) performance, not /devices/. PLAN-055 claims migration 0405; PLAN-044 now owns 0406 for its authorized bulk attribution function, so PLAN-049 must rebase and use 0407 or later. PLAN-019 F05 owns closed-finding retention.
- Resume gate: Implemented, validated locally and committed on branch plan049-active-findings-index (4cb502e0); worktree is absent. Rebase after PLAN-044's migration 0406, renumber this migration to 0407 or later, then release with approval of the pending migrations and a read-only post-deploy plan check.
- Last checked: 2026-11-09 (branch still contains migration 0404 at 4cb502e0; 0405 is now on master; PLAN-044 has assigned migration 0406. Its rebase and renumber remain pending).

## PLAN-050 — Database memory and host capacity

- Scope: Size PostgreSQL memory to the Ninja Dashboard working set on a host with enough headroom not to swap; configuration managed in the repository; any change applied only in an approved maintenance window.
- Status: ready
- Defined: 2026-11-03
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-050-database-memory-and-host-capacity.md
- Source: docs/plans/PLAN-050-database-memory-and-host-capacity.md
- Section: PLAN-050 — Database memory and host capacity
- Related plans: Found by PLAN-049. PLAN-047 and PLAN-048 shrink the working set first; PLAN-042/PLAN-044 timings were taken under the current settings; PLAN-041 owns host CPU.
- Resume gate: Step 1 (read-only host and database measurements) needs read-only production approval; every configuration or host change and any restart is separately approved.
- Last checked: 2026-11-03 (shared_buffers 128 MB for a 31 GB database; host 35 GB with about 4.7 GB available and swap fully used; host shared with Zabbix and Graylog).

## PLAN-053 — Ninja activity retention

- Scope: Bound how long ninja_activities.activities keeps Ninja activity events (774k rows, 7.0 GB, no deletion today), keeping the device timeline, patch activity search and the activity rollup views working; measure first, then decide a period, implement a batched delete and clean up once.
- Status: ready
- Defined: 2026-11-04
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-053-ninja-activity-retention.md
- Source: docs/plans/PLAN-053-ninja-activity-retention.md
- Section: PLAN-053 — Ninja activity retention
- Related plans: Moved from PLAN-019 (received from PLAN-022's backlog). PLAN-050 (database memory) and PLAN-041 (host CPU) benefit; PLAN-047 owns write churn.
- Resume gate: Step 1 (read-only production measurement) needs read-only production approval; the retention decision, implementation, the one-time delete and any table rewrite are each separately approved.
- Last checked: 2026-11-04 (readers: device timeline, patch activity search, three materialized views refreshed after each activities run).

## PLAN-054 — Source collection deadlock repair

- Scope: Coordinate source/software writes with ownership and findings work to prevent the PLAN-045 deadlocks.
- Status: active
- Defined: 2026-11-04
- Started: 2026-11-04
- Completed: —
- Blueprint: docs/plans/PLAN-054-source-collection-deadlock.md
- Source: docs/plans/PLAN-054-source-collection-deadlock.md
- Section: PLAN-054 — Source collection deadlock repair
- Related plans: PLAN-045 introduced invalidation; PLAN-019 closed after collection recovered. Earlier local notes called this PLAN-052, which the remote registry assigned to unrelated Ninja VM analysis.
- Resume gate: Release 0.144.2 committed and pushed with approval; next observe scheduled source runs. Manual collection, further production mutations, commits and pushes require their own authorization.
- Last checked: 2026-11-04 (0.144.2 `fb823658` pushed to both remotes and deployed by Portainer; 49 focused tests pass. Ingest/Jobs version and health verified; readiness and Operations health pass. No new deadlocks observed; source collection recovery and workload waits remain unverified. Earlier local PLAN-052 ID conflicted with an unrelated remote plan; release uses PLAN-054).
