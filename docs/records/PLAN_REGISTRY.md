# Plan registry

## PLAN-055 — Jobs execution-scope claim race

- Scope: Prevent a queued Jobs successor from being claimed while the same tenant/job/scope has an active run; preserve workflow dependencies, request coalescing, and resource capacity.
- Status: completed
- Defined: 2026-11-05
- Started: 2026-11-05
- Completed: 2026-11-05
- Blueprint: docs/plans/PLAN-055-jobs-execution-scope-claim-race.md
- Source: docs/plans/PLAN-055-jobs-execution-scope-claim-race.md
- Section: PLAN-055 — Jobs execution-scope claim race
- Related plans: PLAN-045 introduced ownership successors and is complete; PLAN-054 owns source-write lock ordering. PLAN-049 has a conflicting planned migration 0404 and must follow PLAN-055's migration 0405 as 0406 or later.
- Resume gate: —
- Last checked: 2026-11-05 (0.144.10 / `d139bacb` deployed to origin and mirror; migration 0405 applied; Operations, ingest, and Jobs worker are healthy. Installed v6/v7 definitions contain the active-scope guard. Two successors remain queued behind fresh active runs; a post-deployment successor completion cycle has not yet been observed.)

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


## PLAN-052 — Ninja VM guest records: withdrawn volume and unmatched health rows

- Scope: Explain and, if wrong, fix why most Ninja VM guest device records are withdrawn and why VM guest device-health rows outnumber VM guest device records; decide whether long-withdrawn VM records need a retention rule.
- Status: ready
- Defined: 2026-11-04
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-052-ninja-vm-guest-records.md
- Source: docs/plans/PLAN-052-ninja-vm-guest-records.md
- Section: PLAN-052 — Ninja VM guest records: withdrawn volume and unmatched health rows
- Related plans: Found by a PLAN-019 read-only count. PLAN-038 owns the device-health companion model; PLAN-019 Step 4 records presence changes.
- Resume gate: Step 1 (read-only production diagnosis) needs read-only production approval; any fix, retention rule, migration or release is separately approved.
- Last checked: 2026-11-04 (vm.guest devices 2,704 with 2,006 withdrawn; vm.guest health 3,453, 749 more than devices; agent.rmm health matches devices).


## PLAN-051 — Retire the device layer tables

- Scope: Stop writing and then retire assets, os_instances, agent_instances and their field-history tables (ADR-0013), keeping the data-quality Issues that share the resolver step and archiving the data before the drop.
- Status: ready
- Defined: 2026-11-03
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-051-retire-device-layer-tables.md
- Source: docs/plans/PLAN-051-retire-device-layer-tables.md
- Section: PLAN-051 — Retire the device layer tables
- Related plans: Found by PLAN-012 gate item 5. PLAN-045 edits the same resolver promotion code (rebase after it lands); PLAN-034 owns archive retention; PLAN-008 retired Metabase.
- Resume gate: Step 1 (release A: separate the data-quality Issues, remove the layer writers) needs implementation approval; each release, the archive and the drop are separately approved.
- Last checked: 2026-11-03 (no readers, foreign keys, dependent views or findings references; resolver writes about 1,700 rows in 13 days; _sync_device_attributes also raises four data-quality Issue types).


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


## PLAN-049 — Index active findings by subject

- Scope: Partial index on active findings by subject (migration 0404) and a page-id probe in the /devices/ Computers page so severe-Issue counts read only active findings.
- Status: active
- Defined: 2026-11-03
- Started: 2026-11-03
- Completed: —
- Blueprint: docs/plans/PLAN-049-active-findings-index.md
- Source: docs/plans/PLAN-049-active-findings-index.md
- Section: PLAN-049 — Index active findings by subject
- Related plans: Found by PLAN-012's follow-up review. PLAN-042/PLAN-044 own the Coverage-view (/inventory/computers/) performance, not /devices/. PLAN-055 claims migration 0405; this plan must rebase and renumber its migration to 0406 or later. PLAN-019 F05 owns closed-finding retention.
- Resume gate: Implemented, validated locally and committed on branch plan049-active-findings-index (4cb502e0, worktree .work/plan049); not merged. Next: rebase after PLAN-055's migration 0405, renumber this migration to 0406 or later, then release with approval of the pending migrations and a read-only post-deploy plan check.
- Last checked: 2026-11-03 (devices_page severe-findings subquery 2.3 s reading all 29,557 active severe findings; Operations suite failures identical to the branch base).


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


## PLAN-046 — Authority belongs to the record type

- Scope: Replace per-source-instance attribute authority with record-type authority (complete by construction) plus attribute exceptions; evidence stops carrying a copy of policy; operators manage rules in Operations; per-instance overrides only where production shows a real difference.
- Status: ready
- Defined: 2026-11-03
- Started: —
- Completed: —
- Blueprint: docs/plans/PLAN-046-record-type-authority.md
- Source: docs/plans/PLAN-046-record-type-authority.md
- Section: PLAN-046 — Authority belongs to the record type
- Related plans: Found by PLAN-012's post-release check (ADR-0053). PLAN-045 is changing related ingest and Operations files: work in a separate worktree and rebase migrations after PLAN-045's 0401–0403 land. PLAN-026 owns the source configuration UI.
- Resume gate: Step 1, a read-only production inventory of rules per record type and instance, needs read-only production approval; implementation, migrations, rehearsal and release are separately gated.
- Last checked: 2026-11-03 (two enabled instances have no rules: AMROSE ScreenConnect, 4,779 records; R-U-ON, 728; 764 of 1,208 Unknown-OS Computers have an ignored OS claim).

## PLAN-045 — Source-derived Computer client

- Scope: Reconcile Computer client ownership in a coalesced dirty-only Jobs workflow after source and identity updates, with a separate daily full sweep for anti-entropy; retain human decisions and explicit unresolved states. Bound ownership projection to one Computer per guard transaction and remove the observed Jobs-dependency N+1 scan that holds the same guard.
- Status: completed
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: 2026-11-05
- Blueprint: docs/records/PLAN-045-active-checkpoint.md
- Source: docs/plans/PLAN-045-source-derived-computer-client.md
- Section: PLAN-045 — Source-derived Computer client
- Related plans: PLAN-004 owns source associations and identity; PLAN-015 owns separately approved identity repairs; PLAN-036 supplies record-first evaluation. PLAN-054 repairs source-write lock ordering; PLAN-045 now bounds projector transactions without changing that guard contract. This plan changes client ownership projection, not duplicate merges.
- Resume gate: —
- Last checked: 2026-11-05 (0.144.8 `60ddb296` deployed to origin and mirror; SentinelOne collected 4,487 source observations, its ownership successor completed without waiting for the resolver, dirty rows returned to 0, platform health completed in 17 seconds versus 6 minutes 23 seconds on 0.144.7, and no deadlocks were logged in the preceding 15 minutes. A one-time Jobs claim unique-key violation restarted the worker; it recovered healthy and the queue follow-up is recorded in TODO.md).

## PLAN-044 — Navigation and Computers performance

- Scope: Achieve ordinary Home response time ≤1.5 seconds (2.0-second hard maximum), preserving the agreed domain-owned Operations overview, supported trends of 30 days or less, current Coverage totals without a separate Home trend, and detailed client portfolio on Clients.
- Status: active
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-044-page-performance.md
- Section: PLAN-044 — Navigation and Computers performance
- Related plans: PLAN-042 supplies prior performance evidence; PLAN-012 retains Computer semantics and verification; PLAN-043 independently owns issue review in views.py. PLAN-019 source-record history is now complete and available. PLAN-003/004 contracts remain unchanged.
- Resume gate: User authorized autonomous measurement, focused fixes, validation, commit/push, and then explicitly authorized live-production measurement on 2026-11-09. Keep measurements bounded to ordinary read-only page requests and diagnostics; preserve the approved Home design and no-schema approach. Review automatic deployment effects and the pending migration set before an `origin` push.
- Last checked: 2026-11-09 (`5b976ed4` deployed; Operations healthy, no migrations pending. Authenticated Home still timed out; combined compact query ran over 108 seconds and was canceled. Production EXPLAIN located a repeated sequential scan of 5,718 ownership rows in the correlated owner check. A tenant-scoped owner join is under development; pending commit and measurement. See detailed handoff).

## PLAN-043 — Useful issue review

- Scope: Explain issues, display safe source-record identity evidence and comparisons, and expose existing permission-checked resolution paths on the review page.
- Status: completed
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: 2026-11-02
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-043-issue-review.md
- Section: PLAN-043 — Useful issue review
- Related plans: PLAN-003/004 supply completed finding/action and source-record contracts; PLAN-015 owns identity repairs and PLAN-016 owns the SQL explorer. This plan only reads their data and does not change those mechanisms.
- Resume gate: Local UI implementation complete. Release 0.143.2 commit and push approved 2026-11-02, including automatic deployment. No pending migrations, schema, identity-policy or production-data changes.
- Last checked: 2026-11-02 (14 new tests pass; focused run 49 passed and one pre-existing source-text failure; staged read-only render of linked finding succeeds with two Computers and four source records. Evidence and limitations retained in the plan).

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

## PLAN-040 — Source-record notifications

- Scope: Enable useful alerts for PLAN-004's native record/case findings without migration spam, restricted-context disclosure, lost ongoing alerts or unreviewed policy changes.
- Status: deferred
- Defined: 2026-10-29
- Started: —
- Completed: —
- Blueprint: —
- Source: operations/docs/plans/PLAN-040-source-record-notifications.md
- Section: PLAN-040 — Source-record notifications
- Related plans: Deferred from PLAN-004 revision 8; coordinate PLAN-003 and the other PLAN-039/040 follow-up before overlapping changes. Neither follow-up blocks the smaller PLAN-004 release.
- Resume gate: PLAN-004 foundations available and explicit user approval to resume this concrete follow-up; reconcile current implementation and approve requirements/design before implementation or production execution.
- Last checked: 2026-10-29 (plan defined only; no implementation, tests or production operations).
- Renumbered: 2026-11-02 from PLAN-034 (collision with the registry's PLAN-034); PLAN-003/004 design records written before 2026-11-02 were updated to the new number.

## PLAN-039 — Source-record case combining

- Scope: Combine related source-record investigations only when operators need one same-problem/same-action workspace beyond PLAN-004's related-case display.
- Status: deferred
- Defined: 2026-10-29
- Started: —
- Completed: —
- Blueprint: —
- Source: operations/docs/plans/PLAN-039-source-record-case-combining.md
- Section: PLAN-039 — Source-record case combining
- Related plans: Deferred from PLAN-004 revision 8; coordinate PLAN-003 and the other PLAN-039/040 follow-up before overlapping changes. Neither follow-up blocks the smaller PLAN-004 release.
- Resume gate: PLAN-004 foundations available and explicit user approval to resume this concrete follow-up; reconcile current implementation and approve requirements/design before implementation or production execution.
- Last checked: 2026-10-29 (plan defined only; no implementation, tests or production operations).
- Renumbered: 2026-11-02 from PLAN-033 (collision with the registry's PLAN-033); PLAN-003/004 design records written before 2026-11-02 were updated to the new number.

## PLAN-038 — Ninja device health as detail of the device record

- Scope: Ninja device health becomes a companion data set of the Ninja device record (ADR-0051): never a source record or link of its own, attached to and withdrawn with its device record; retire the 8,513 health records and 7,330 links; show health on the device record.
- Status: completed
- Defined: 2026-11-02
- Started: 2026-11-02
- Completed: 2026-11-02
- Blueprint: —
- Source: docs/plans/PLAN-038-ninja-device-health-as-record-detail.md
- Section: PLAN-038 — Ninja device health as detail of the device record
- Related plans: PLAN-004 owns source records (migration 0370 admission); PLAN-033 reads device health; the TODO Sources page double-count item is folded in.
- Resume gate: None; complete.
- Last checked: 2026-11-02 (0.141.0 `6a6355ac` deployed; 0 health records and links, 6,090 attached, health claims on the device record's Computer, first health run attached 5,608).

## PLAN-037 — Source collection failures

- Scope: Make every open source-failure Issue reflect a current failure: find why completed collections leave Issues open, fix or retire the ThreatFox collector (410 Gone), close the retired agent_compliance failure, stop deploy-interrupted runs from raising failures, and review Ninja's failed required steps.
- Status: active
- Defined: 2026-11-01
- Started: 2026-11-01
- Completed: —
- Blueprint: docs/plans/PLAN-037-source-failures.md
- Source: docs/plans/PLAN-037-source-failures.md
- Section: PLAN-037 — Source collection failures
- Related plans: PLAN-036 owns the admin-finding clear assessments the guard uses; PLAN-019 F09 and the TODO Ninja collection-gap item overlap Step 5.
- Resume gate: Each step needs user approval; Step 1 is read-only.
- Last checked: 2026-11-02 (read-only: Steps 1–3 done; 0.142.0 ThreatFox run completed 17:53 UTC; Step 5 failures stopped before 0.142.0, first Ninja run on it completed 18:20 UTC; Step 4 approved and implemented locally 2026-11-02, unreleased).

## PLAN-036 — Record-first findings and consistent identity decisions

- Scope: Finalize ADR-0050; implement automatic source-record risk findings and consistent PLAN-004 §5 association decisions, with the related findings presentation and handover.
- Status: completed
- Defined: 2026-10-30
- Started: 2026-10-30
- Completed: 2026-11-02 (released 0.138.0–0.139.1; follow-ups 0.141.1–0.141.2 register the per-source software tables and let recovered health Issues close; verified read-only 2026-11-02)
- Blueprint: docs/plans/PLAN-036-record-first-findings.md
- Source: docs/plans/PLAN-036-record-first-findings.md
- Section: PLAN-036 — Record-first findings and consistent identity decisions
- Related plans: PLAN-003 owns common findings and queue; PLAN-004 owns source records and identity. This continuation completes their identified gaps, with record-level findings before stricter association policy.
- Resume gate: None; complete.
- Last checked: 2026-10-30 in `plan003-r3` at `253db218`. Core ADR-0050 implementation is locally validated (evidence in handoff). Follow-up implementation aligns the client dashboard's unresolved mapping count with the Issues independent-action selection and closes stale per-group `client_unattached_group`, `unnamed_source_group`, and non-topology `client_link_collision` findings with closure reasons. Admin findings require current-observation clear assessments; unnamed entity findings close only open/acknowledged episodes when source state no longer meets the condition. 60 focused ingest tests and 21 focused Operations queue/client-mapping tests pass; Python compilation, scoped Ruff for changed ingest files, and `git diff --check` pass. Whole-file Ruff on the large views module still reports existing findings; the full Operations suite was not run. `scripts/validate_plan_registry.py` is absent from this checkout, so registry structure was manually reconciled. PLAN-004 production reassessment review and R4-2 post-release timing/queue observation remain outstanding and gated; no production, commit, push or deployment action occurred. See the handoff for scope, decisions, and evidence.
- Last checked: 2026-11-02 (production read-only: source-record queue drained, 0 intake errors, resolver 51/51 completed in 24 h, relationship and attribute queues empty, active policy conditions-registry-14, evaluations 5–8 min, 0 open health Issues without a current assessment).

## PLAN-035 — Health enrichment evidence classification

- Scope: Give Ninja health observations a dedicated non-identity evidence type, preserve health claims and consumers, and consistently exclude enrichment from Computer source-record populations.
- Status: superseded
- Defined: 2026-10-29
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/plans/PLAN-035-health-enrichment-evidence-classification.md
- Section: PLAN-035 — Health enrichment evidence classification
- Related plans: PLAN-007 owns collection/enrichment separation; PLAN-012 owns broader inventory populations, including Hudu relevance; PLAN-004 owns identity and record maintenance; PLAN-019 owns observation history and publication safeguards. Agree ownership and sequence with those plans before modifying shared writers, readers, policies, or history. This plan does not resume their gated work.
- Resume gate: Superseded by PLAN-038 on 2026-11-02: health became a companion data set of the Ninja device record (ADR-0051) instead of a dedicated evidence type. Do not resume; preserve this source for provenance.
- Last checked: 2026-10-29. Local architecture/writer review and read-only aggregate production investigation completed; plan created without runtime changes. Current checkpoint and validation requirements are in the source document.

## PLAN-034 — Post-cleanup housekeeping: notification settings and rollback archives

- Scope: Rename the host `.env` `AGENT_COMPLIANCE_*` notification delivery keys to `NOTIFY_*`, and decide retention for the PLAN-022 and Metabase rollback archives.
- Status: deferred
- Defined: 2026-10-28
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/plans/PLAN-034-post-cleanup-housekeeping.md
- Section: PLAN-034 — Post-cleanup housekeeping: notification settings and rollback archives
- Resume gate: Each step needs user approval; the host `.env` change is a production write, and deleting an archive is destructive.
- Last checked: 2026-10-28 (registered from the backlog; no work started).

## PLAN-033 — Patching and device-health reporting gaps

- Scope: Show patch warning analysis, reboot, operational-failure and MANUAL-age trends, and Ninja device health in Operations; then retire the 8 Metabase-era ingest views that back them.
- Status: deferred
- Defined: 2026-10-28
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/plans/PLAN-033-patching-and-device-health-reporting.md
- Section: PLAN-033 — Patching and device-health reporting gaps
- Resume gate: The user decides what operators need (Step 1) and approves each build step. Feature work; not approved.
- Last checked: 2026-10-28 (registered from the backlog; gaps found by the PLAN-022 view review).

## PLAN-032 — Per-instance source display titles

- Scope: Display the configured source-instance name on the Sources page while retaining the catalog name for shared source-mapping identity.
- Status: completed
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: 2026-10-28
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-032 — Per-instance source display titles
- Related plans: PLAN-025 established the ScreenConnect source contract; PLAN-026 remains the separate source-configuration UI plan. This label correction is independent of PLAN-030 bulk candidate acceptance.
- Resume gate: Complete. AMROSE is configured as `AMROSE ScreenConnect`; the Sources page uses each instance display name and keeps catalog identity for mapping filters. Commit `9aef8fc` is an ancestor of both `origin/master` and `a-m-rose/master`. No migration was required.
- Last checked: 2026-10-28. Python compilation and staged whitespace validation passed; tests were not run. Remote tips were verified read-only. Live browser verification remains unconfirmed.

## PLAN-031 — Source record and reported states

- Scope: Distinguish source-record presence from each record's reported online state in Operations.
- Status: completed
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: 2026-10-28
- Blueprint: —
- Source: operations/docs/records/PLAN-031-source-record-states.md
- Section: PLAN-031 — Source record and reported states
- Related plans: PLAN-012 owns broader source-record reads and performance; this change appends one safe metadata field and preserves its existing query contract.
- Resume gate: Complete; authenticated browser review remains unverified.
- Last checked: 2026-10-28. Commit `b393c57` deployed; migrations 0358–0360 applied, application check passed, and source-specific online states were verified under the runtime role. See the record for limitations.

## PLAN-030 — Bulk accept discovered client candidates

- Scope: Let Operations users create new clients from a selected set of open source-client candidates in one reviewed, audited action.
- Status: completed
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: 2026-10-30
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-030 — Bulk accept discovered client candidates
- Related plans: PLAN-004 retains identity matching policy; PLAN-029 surfaced the local first-ingest candidate backlog. This plan only batches the existing operator-approved accept-as-new action and does not change matching or mapping rules.
- Resume gate: None. Released in 0.133.0 (`020cf560`) with the findings guard added for PLAN-003 R2; deployed to origin and the mirror, Operations healthy, contract 4, routes resolve.
- Last checked: 2026-10-30. Production deploy of 0.133.0 verified: Operations, ingest and Jobs worker healthy; Inventory → Clients, Client mappings and the bulk-accept route respond (sign-in redirect). Operations unit suite shows only failures pre-existing on master. No candidate was accepted during verification.

## PLAN-029 — Jobs readiness and first ingest

- Scope: Keep scheduler health current with scheduled work disabled and satisfy Ninja reference-data prerequisites before manual device ingestion.
- Status: active
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-029-jobs-readiness-and-first-ingest.md
- Section: PLAN-029 — Jobs readiness and first ingest
- Related plans: PLAN-027 provides isolated local services; PLAN-028 keeps local configuration full parity except scheduled Jobs.
- Resume gate: Implementation is authorized. Do not rerun source collections or notification jobs during validation.
- Last checked: 2026-10-28. Diagnosis confirmed stale scheduler heartbeat with schedule gate off and missing Ninja location reference during device upsert.

## PLAN-028 — Local production configuration parity

- Scope: Use production-equivalent source and notification configuration locally while preserving local database credentials and disabling scheduled Jobs.
- Status: completed
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: 2026-10-28
- Blueprint: —
- Source: docs/plans/PLAN-028-local-prod-config-parity.md
- Section: PLAN-028 — Local production configuration parity
- Related plans: PLAN-027 provides the isolated local Compose stack. Preserve its local database, login, port, and volume isolation.
- Resume gate: Configuration work is complete. Preserve local database/admin credentials and `SCHEDULED_JOBS_ENABLED=false`; use the documented merge before local manual source/jobs runs. Manual runs may access production endpoints and send configured notifications.
- Last checked: 2026-10-28. Compose rendering and registry validation passed at completion. Local Operations, ingest, and Jobs worker were up; login and Django checks passed; scheduled Jobs were disabled. No source or notification jobs ran during this configuration work. The separate ScreenConnect activation and collection belong to PLAN-025.

## PLAN-027 — Isolated local development stack

- Scope: Provide a complete local Compose stack with isolated storage and credentials, manual source collection, and local migration validation before production deployment.
- Status: completed
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: 2026-10-28
- Reopened: 2026-10-28 (dev `/orgs/all/` request failed because `operations_app` lacked `USAGE` on `ninja_core`)
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-027-local-development-stack.md
- Section: PLAN-027 — Isolated local development stack
- Related plans: PLAN-026 owns a future source-configuration UI; local source bindings must use the existing supported configuration path and must not expand that UI plan.
- Resume gate: Dev-only grant repair is authorized. Production reads/writes, collection, commits, pushes, and deployment are outside scope and retain separate approval requirements.
- Last checked: 2026-10-28. Dev Compose startup completed; grant service exited 0, exact directory query passed under `operations_app`, and Operations logged authenticated `/orgs/all/` HTTP 200. Django system check and Compose rendering pass. Production files and migrations are unchanged.

## PLAN-026 — Source configuration UI

- Scope: Add an administrator UI to create supported source instances and collector bindings with safe defaults.
- Status: active
- Defined: 2026-10-28
- Started: —
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-026-source-configuration-ui.md
- Section: PLAN-026 — Source configuration UI
- Related plans: PLAN-025 supplies the shared ScreenConnect configuration contract; source UI work must preserve its connector and grouping behavior without reopening its discovery scope.
- Resume gate: Begin implementation after explicit user approval. First reconcile PLAN-025's current registry/checkpoint and Git state, then confirm the supported source allowlist and existing schema/runtime requirements. Production source/binding writes, activation, first collection, commit, and deployment remain separately authorized.
- Last checked: 2026-10-28. Planning only. Existing models cover source instances and collector bindings; `/sources/` supports refresh and schedule controls but no create flow. No application code or schema changed for this plan. PLAN-025 created and activated the AMROSE source, completed its first source refresh, and the user later set its schedule to every four hours through `/sources/`.

## PLAN-025 — Shared ScreenConnect and Operations inventory summary

- Scope: Identify the restored ScreenConnect customer-group contract, support shared-instance group evidence, and show deduplicated Operations Computer statuses with matching drill-throughs.
- Status: completed
- Defined: 2026-10-27
- Started: 2026-10-27
- Completed: 2026-10-28
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-025 — Shared ScreenConnect and Operations inventory summary
- Related plans: PLAN-012 owns broader inventory semantics; this bounded addition reuses its current Computer population and status filters without resuming its gated redesign. PLAN-004/007/019 retain identity, writer, and pipeline policy; preserve their contracts and existing dirty edits.
- Resume gate: Implement and validate locally after read-only discovery. Source configuration writes, migrations, commits, pushes, and deployment retain separate approval.
- Last checked: 2026-10-28. Shared custom-property support and Operations card remain local; 8 focused ScreenConnect tests pass. A read-only request returned 4,511 Access sessions (4,506 active hosts). CustomProperty1 had 125 distinct values; 83 matched Ninja organization names case-insensitively and 85 after punctuation-insensitive normalization (78 Ninja organizations). CustomProperty2 had 7 case-insensitive matches across 90 values; other populated properties had little/no overlap. User notes Company appears to drive ScreenConnect's customer containers. Session payloads expose no explicit group-named field, and a direct read-only `GetSessionGroups` call to the RESTful API Manager endpoint returned HTTP 500 without definitions. Of 4,506 active hosts, 84 lack Company; preserve those sessions as source evidence without an empty-name org/container or group-based client mapping. Existing identity resolution may still associate an observation to a client when it matches a known Computer. Company/CustomProperty1 remains the best-supported customer grouping field; the container definitions themselves are not yet retrieved. No shared source record exists. Operations tests cannot start locally because the `shared` Python package imported by `operations/apps/core/admin.py` is absent. No production source configuration, collection, or migration was performed. Find a supported group-definition read path and review unmatched Company values before requesting shared source configuration or collection.

This is the repository authority for the status of substantial work. Archive
files preserve their detailed reasoning and evidence; they are current only
when an entry below names them. `BLUEPRINT.md` is required only while an
`active` plan is being executed.

Statuses: `active` (executing under a blueprint), `ready` (resumable after its
gate), `verify` (preserved but needs current corroboration), `deferred`,
`completed`, `superseded`, and `archived-only`.

Multiple plans may be `active` when their scopes are independent. Each active
plan must name its own blueprint. Plans with overlapping scopes must name the
other plan and state their dependency or execution order in their resume gate;
do not open competing blueprints for the same work.

## PLAN-001 — Dashboard navigation performance

- Scope: Root and Operations performance
- Status: completed
- Defined: 2026-10-13
- Started: 2026-10-13
- Completed: 2026-10-21
- Blueprint: BLUEPRINT.md
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Dashboard navigation performance
- Resume gate: No action. A new approved plan is required for a shared inventory read model or any change to the full-fleet filter/card contract.
- Last checked: 2026-10-21 (releases 0.128.14 and 0.128.15 reduced Computers browser first response from 6.351 s to 4.740 s. The remaining below-target result is a measured, explicitly deferred architecture exception in `BLUEPRINT.md`).

## PLAN-002 — Source-driven collection and Jobs recovery

- Scope: Cross-service collection and Jobs
- Status: completed
- Defined: 2026-10-08
- Started: 2026-10-08
- Completed: 2026-10-26
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — source-driven collection
- Resume gate: No action. The recovered Ninja source refresh completed and published output after the worker remained healthy; source-specific endpoint health is tracked separately. Newer pipeline-correctness findings remain with PLAN-019.
- Last checked: 2026-10-26 (read-only production verification). The Ninja source refresh requested at 21:36 UTC started at 21:43 and completed at 22:07 with a published output. Its Jobs worker had been healthy since 21:12 UTC with zero container restarts. The earlier run and its single recovery retry both recorded worker shutdown interruption, consistent with redeploys. The separate `reference.abusech` endpoint failure is tracked independently. See `docs/records/PLAN-002-verification-2026-10-26.md`.

## PLAN-003 — Central work queue and finding state

- Scope: Operations findings workflow
- Status: completed
- Defined: 2026-10-14
- Started: 2026-10-15
- Completed: 2026-10-30 (R1–R3 released; PLAN-003 implementation complete)
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-003-current-design.md
- Section: PLAN-003 — Issues queue current design
- Resume gate: None for PLAN-003. Its client dashboard count alignment is complete locally under PLAN-036; new changes require a separately scoped plan.
- Last checked: 2026-10-30. R1–R3 are released through 0.134.1; R3 supplies the unified Issues selection, independent action keys, covered evidence navigation, and queue counts. PLAN-003 is complete; its scoped client dashboard action-count follow-up is implemented locally under PLAN-036. Older active/design-phase status text in the Operations blueprint and design introduction was stale and has been reconciled. See the current design and PLAN-036 handoff for evidence.

## PLAN-004 — Computer identity, history, and naming

- Scoped repair: operations/docs/plans/PLAN-004-source-record-status.md — per-record status/contact is complete locally; scoped commit approved, push/deployment remain gated.
- Scope: Operations identity lifecycle
- Status: completed
- Defined: 2026-10-16
- Started: 2026-10-16
- Completed: 2026-11-02 (R4 released 0.135.0–0.137.0; reassessment rows recorded as dispositions in 0.139.0 — 1,271 kept, none moved; post-release timing/queue check found and fixed the evaluator lock time and relationship projection in 0.139.2–0.140.0; verified read-only 2026-11-02)
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-004-source-record-review.md
- Section: Computer identity and platform change history (2026-10-16); How a Computer is named — ADR-0034 proposal (2026-10-19)
- Resume gate: None; complete. Deferred PLAN-004 items (PLAN-039/040 plans, measured optimizations) stay in operations/TODO.md.
- Last checked: 2026-10-20 (live). Identity relations are present; 32 merges occurred in seven days and seven name collisions remain. This confirms activity, not completion of the follow-up plan.
- Last checked: 2026-10-30. R4 (final design rev 8) released: 0.135.0 managed subjects/rules (+0.135.1 Jobs resource-limit hotfix), 0.136.0 one-key cases, 0.137.0 link authority in a drained window with backup; one-time reassessment run (results in operations/BLUEPRINT.md). Follow-ups in operations/TODO.md.
- Follow-up added 2026-10-26, implemented locally under PLAN-036 on 2026-10-30: reconcile `client_unattached_group`, `unnamed_source_group`, and per-group `client_link_collision` at the end of each client-resolver run when a group is assigned, inactive, gone, renamed, or no longer matches two or more clients. Record a closure reason. Topology collision findings are preserved; entity-candidate withdrawal remains tracked separately under PLAN-021.
- Last checked: 2026-11-02 (production read-only: source-record queue drained, 0 intake errors, resolver 51/51 completed in 24 h, relationship and attribute queues empty, active policy conditions-registry-14, evaluations 5–8 min, 0 open health Issues without a current assessment).

## PLAN-005 — Jobs observability and schedule authority

- Scope: Operations Jobs
- Status: verify
- Defined: 2026-10-19
- Started: 2026-10-19
- Completed: —
- Blueprint: —
- Source: operations/docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Jobs observability and maintenance cadence (2026-10-19); Schedule retirement authority (2026-10-19)
- Resume gate: Verify the remaining health/schedule follow-ups against current Jobs behavior before treating them as open work.
- Last checked: 2026-10-20 (live). All 24 enabled schedules have no overdue next run; durable Jobs had 4,117 completed, 109 failed, and 38 stalled runs in seven days, so the plan remains unresolved.
- Received from PLAN-022 (2026-10-28): the two run logs, `ninja_core.run_log` and `operations.run_log`. Both are still written, so this is a design question (one run authority), not a cleanup.

## PLAN-006 — Legacy agent-compliance retirement

- Scope: Root and Operations platform cleanup
- Status: superseded
- Defined: 2026-10-13
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/backlog.md
- Section: Legacy agent-compliance cutover
- Resume gate: Superseded by PLAN-022 on 2026-10-26 (user approved immediate legacy cleanup, including agent compliance).

## PLAN-007 — Ingest domain separation

- Scope: Ingest architecture
- Status: deferred
- Defined: 2026-06-19
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/backlog.md
- Section: Ingest domain separation
- Resume gate: Approve extraction of shared scheduler/bootstrap ownership.
- Received from PLAN-022 (2026-10-28): the remaining `ninja_core` staging
  tables (`devices` at 1.5 GB, policies, custom fields, `software_activity_queue`,
  `ingest_state`) and the `*_shadow` compatibility views. They are still read,
  so they retire as their readers move, not by cleanup.
- Received from the backlog (2026-10-28, from PLAN-022): the two migration
  tracks (`sql/migrations` with `ninja_core.schema_migrations`, and Django).
  Decide whether to consolidate. Design item; not approved.

## PLAN-008 — Metabase retirement

- Scope: Retired reporting runtime
- Status: completed
- Defined: 2026-10-12
- Started: 2026-10-12
- Completed: 2026-10-12
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Completed plan — Metabase retirement
- Resume gate: No action; any rollback or archive destruction requires a new approved plan.
- Last checked: 2026-10-20 (live). No Metabase container is running; the replacement ingest, Operations, Jobs worker, and Postgres containers are healthy.

## PLAN-009 — Plan-status governance

- Scope: Repository documentation governance
- Status: completed
- Defined: 2026-10-20
- Started: 2026-10-20
- Completed: 2026-10-20
- Blueprint: BLUEPRINT.md
- Source: docs/records/CLEANUP_SUMMARY-2026-10-20.md
- Section: Remaining intentional workspace material
- Resume gate: Complete registry/backlog validation and record the outcome in the blueprint.

## PLAN-010 — Work-status reconciliation

- Scope: Repository and Operations documentation governance
- Status: completed
- Defined: 2026-10-20
- Started: 2026-10-20
- Completed: 2026-10-20
- Blueprint: BLUEPRINT.md
- Source: docs/records/PLAN_REGISTRY.md
- Section: PLAN-010 — Work-status reconciliation
- Resume gate: No action; select a `ready` plan or perform the recorded verification gate for a `verify` plan.

## PLAN-011 — Software inventory and findings rebuild

- Scope: Operations software inventory and findings
- Status: completed
- Defined: 2026-10-13
- Started: 2026-10-13
- Completed: 2026-10-13
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Software inventory ingest rebuild; Active plan — Software findings rebuild (implementation)
- Resume gate: No action; open a new plan only for a verified follow-up not covered by the 0.127.0 release.

## PLAN-012 — Computers inventory read model

- Scope: Operations Computers inventory performance
- Status: completed
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: 2026-11-03
- Blueprint: BLUEPRINT.md
- Source: docs/records/PLAN-012-computer-read-checkpoint.md
- Section: PLAN-012 — Computer reads and inventory checkpoint
- Resume gate: No action. Released in 0.143.0 (6f587fae); verified in production. Durable decision: ADR-0053. Follow-ups are in TODO.md; the authority gap found after release is PLAN-046.
- Last checked: 2026-11-03 (both Computers created after the deploy had their claims on the new Computer and values selected in the creating transaction; one stayed Unknown only because its source instance has no authority rules, PLAN-046).

## PLAN-013 — Operations sign-in page

- Scope: Operations authentication pages
- Status: completed
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: 2026-10-26
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-013 — Operations sign-in page
- Resume gate: No action. Deployed authentication flow verified in the browser.
- Last checked: 2026-10-26 (user-reported browser verification). Sign-in and sign-out passed; the authenticated password-change form displayed its current/new/confirmation fields; after sign-out, `/account/password/` redirected to login. The password was not changed. Operations container was healthy after deployment `b1d3772`, with migrations 0352 and 0353 applied.

## PLAN-014 — Requirement applicability

- Scope: Evaluator coverage rules and Computers requirement display
- Status: completed
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: 2026-10-28
- Blueprint: ingest/BLUEPRINT.md
- Source: ingest/BLUEPRINT.md
- Section: PLAN-014 — Requirement applicability
- Design: docs/plans/PLAN-014-requirement-reconciliation.md. Release `79088db` (0.129.4, migration 0357) was pushed to origin then the mirror; origin push triggered automatic deployment. Acceptance continuation and current evidence are recorded in docs/records/PLAN-014-acceptance-2026-10-27.md.
- Execution order: PLAN-014 repairs evaluator requirement reconciliation before PLAN-003 changes shared finding persistence/relationships. PLAN-003 retains that shared redesign. PLAN-012's ADR-0035 resolution-reader follow-up is handled here only for requirement finding resolution; page readers remain PLAN-012.
- Resume gate: Complete. Commit `79088db` (0.129.4) is on both remotes; origin deployment applied migration 0357. Read-only production verification on 2026-10-28 confirmed healthy stack services, matching deployed file hashes, and zero unexplained drift. No production recalculation was triggered. Browser, stress, and representative synthetic performance checks remain unverified.
- Last checked: 2026-10-28 (latest platform run succeeded; 79 distinct disagreements match recorded drift and are all retained by current guards, with zero requiring review or other disagreement types. Covered findings have active same-tenant/same-subject parents; 100 actionable unknown-OS findings remain within the original estimate. Evidence: docs/records/PLAN-014-acceptance-2026-10-27.md.)

## PLAN-015 — One-time source-record identity reconciliation

- Scope: Read-only fleet preview of which existing source records the current resolver would attach to a different Computer, then separately reviewed and approved repairs.
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-015-identity-reconciliation.md
- Section: PLAN-015 — One-time source-record identity reconciliation
- Resume gate: The preview is read-only; any reattachment, merge or derived-data refresh needs its own approval. Coordinates shared identity code with PLAN-004.
- Last checked: 2026-10-28 (registered from its plan doc, which was untracked; the status is the doc's as of 2026-10-21 and was not re-verified. The doc's next action: review the 110 guard-aware candidates).

## PLAN-016 — Admin read-only SQL explorer

- Scope: Admin-only Operations page for bounded read-only SQL (READ ONLY transaction, tenant 1 forced, short timeout, result limit), with the identity reattachment-candidate query saved.
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/plans/PLAN-016-admin-sql-explorer.md
- Section: PLAN-016 — Admin read-only SQL explorer
- Resume gate: Implementation and deployment need user approval.
- Last checked: 2026-10-28 (registered from its plan doc, which was untracked; the status is the doc's as of 2026-10-21 and was not re-verified. No implementation found in the repository).

## PLAN-017 — Consolidated data architecture review and target design

- Scope: Adopted consolidated architecture, lifecycle, retention, recovery, efficiency, index/view, and A1–A10 review from acquisition through operator results and expiry; assessment and proposed design only, no remediation
- Status: completed
- Defined: 2026-10-23
- Started: 2026-10-25
- Completed: 2026-10-26
- Blueprint: —
- Source: docs/plans/PLAN-017-consolidated-data-architecture-review-draft.md
- Section: PLAN-017 — Consolidated data architecture review and target design
- Original source: operations/docs/plans/PLAN-017-data-architecture-review.md
- Resume gate: None; completed. Phases 1–5 executed with user approvals and two-reviewer agreement (review Points 39–42). Follow-up work is PLAN-019 (ready); F04 stays with PLAN-012 item 4; the retention decision is operations ADR 0045. Writer/refresh/capacity and ordinary-user reader parity were out of scope throughout.
- Last checked: 2026-10-26 (Phase 5 triage agreed as proposals by Codex rounds 23–24; user answered Q1 yes, with a significant-change trail, and Q2 yes. Records: phase-2/3/4 results, phase-5 triage, commits 73cefab, 3f067da, 384b0d2 and the closing commit).

## PLAN-018 — Independent end-to-end data and ingest architecture review

- Scope: Independent end-to-end data and ingest architecture review strictly for data integrity, performance, and avoiding unnecessary duplication; includes collection completeness, authority, constraints, repeated calculations/storage, processing order, and reader consistency
- Status: superseded
- Defined: 2026-10-23
- Started: —
- Completed: —
- Blueprint: —
- Source: docs/plans/PLAN-018-end-to-end-data-ingest-review.md
- Section: PLAN-018 — Independent end-to-end data and ingest architecture review
- Consolidated charter: docs/plans/PLAN-017-consolidated-data-architecture-review-draft.md
- Resume gate: Superseded by PLAN-017 on 2026-10-25 through explicit user adoption of the consolidated charter. Preserve this original source for provenance; resume only through PLAN-017 and its current authorization gates.
- Last checked: 2026-10-25 (absorbed into PLAN-017; source text unchanged. PLAN-018 never independently entered execution, so Started and Completed remain —).

## PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)

- Scope: Fix PLAN-017's confirmed acquisition, publication and retention defects in order: F07 contract, F01 receipt, F02 cap detection and bounded continuation, F03 enqueue order, F09 all-source daily presence (assess first), U04 generation fence with F06 stage map, F08 separate sites scope, and the ADR 0045 first-observed anchor and significant-change trail
- Status: completed
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: 2026-11-04
- Blueprint: docs/plans/PLAN-019-data-pipeline-correctness-and-retention.md
- Source: docs/plans/PLAN-019-data-pipeline-correctness-and-retention.md
- Section: PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)
- Resume gate: Complete. F04 remains with PLAN-012; F05 remains with R08/PLAN-006.
- Last checked: 2026-11-04 (completed through releases 0.144.0/0.144.1; production validation recorded in the plan: activities succeeded, three complete SentinelOne snapshots, migration 0404 applied with first-seen on 34,141 source records. Failed-sites-fetch path remains unit-tested only. F04 stays with PLAN-012; F05 with R08/PLAN-006).
- Activity retention (received 2026-10-28 from PLAN-022) moved to PLAN-053 on 2026-11-04.

## PLAN-020 — Operations entity links in tables

- Scope: Link identifiable client, Computer, and other entity names in Operations tables to their detail pages; retain specific workflow destinations and add useful detail-page breadcrumbs.
- Status: completed
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: 2026-10-26
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/requirements.md
- Section: User interface; Acceptance criteria
- Resume gate: Complete. Link identifiable entities in Operations tables to detail pages, preserve existing workflow destinations, and provide useful breadcrumbs. No schema, migration, commit, or deployment was in scope.
- Last checked: 2026-10-26 (table links and breadcrumbs implemented. Python compilation, plan-registry validation, and `git diff --check` pass; Ruff reports no findings on changed Python lines while full files retain unrelated lint findings. Django system/template checks could not run because Django is not installed on the workstation.)

## PLAN-021 — Generic entity candidate lifecycle reconciliation

- Scope: Reconcile generic entity candidates with current source-observation activity and entity source links, including an auditable withdrawal state and verification/backfill for existing stale candidates.
- Status: completed
- Defined: 2026-10-26
- Started: 2026-10-27
- Completed: 2026-10-27
- Blueprint: BLUEPRINT.md
- Source: operations/docs/plans/PLAN-021-entity-candidate-lifecycle.md
- Section: Generic entity candidate lifecycle reconciliation
- Related plan: PLAN-004 covers client resolver findings; PLAN-021 concerns the separate generic `entity_candidates` projection and state machine.
- Resume gate: Complete. Commit `6add50f` was pushed to `origin` then `a-m-rose`; origin deployment applied migration 0355. The bounded production projector completed one changed batch; read-only aggregate validation confirmed all stale actionable states withdrawn with audit events.
- Last checked: 2026-10-27 (669 withdrawals and events: 592 inactive-unlinked and 77 linked-class conflicts; zero inactive-unlinked actionable candidates, active withdrawn unlinked candidates, or linked class mismatches among pending/observed-only candidates. Sixteen attached-class mismatches remain preserved. Initial aggregate review is in `docs/records/PLAN-021-candidate-review-2026-10-27/`.)

## PLAN-022 — Legacy data and code cleanup

- Scope: Export and remove legacy tables, schemas, views, Jobs and code no current workflow reads: Ninja daily presence, legacy Ninja snapshots, agent compliance (absorbs PLAN-006) and the inventory schema; Wave B items need their own design.
- Status: completed
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: 2026-10-28
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-022-legacy-data-cleanup.md
- Section: PLAN-022 — Legacy data and code cleanup
- Resume gate: User approved immediate execution (2026-10-26). Three separately approved pushes: migration 0349; the code; then the drop migrations 0350, 0351, 117 and 118 after the archive is copied off-host and verified.
- Last checked: 2026-10-28 (Wave B built: `0358` drops `parity_report` and `legacy_job_key`, `0359` drops `metabase_ro`; the review of the 8 Metabase-era views keeps all of them and records the gaps; live items handed to PLAN-005, PLAN-007 and the backlog. Deployed in 0.130.0; `0358`/`0359` applied and verified read-only on production).

## PLAN-023 — Software installations layout repair

- Scope: Align and compact installation filters and bound long install paths within the table; template-only UI changes.
- Status: completed
- Defined: 2026-10-27
- Started: 2026-10-27
- Completed: 2026-10-27
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-023 — Software installations layout repair
- Resume gate: Local implementation complete. Independent of other active plans; no shared view, data, schema, or identity changes. Commit and deployment require separate approval.
- Last checked: 2026-10-27 (four existing tests, Django checks, synthetic Edge layout/interaction checks at four viewport widths, registry, governance and whitespace pass; live deployment unverified).

## PLAN-024 — Preserve Ninja software display names

- Scope: Preserve the original Ninja software `name` alongside the lowercase canonical matching key, and use that source spelling wherever a human sees a software product name across the Operations UI and exports. Canonical values remain the matching, decision, filter, and URL keys. Existing rows fall back to their current canonical spelling until refreshed.
- Status: completed
- Defined: 2026-10-27
- Started: 2026-10-27
- Completed: 2026-10-27
- Reopened: 2026-10-27 (user expanded scope to all human-visible software names)
- Blueprint: operations/BLUEPRINT.md
- Source: operations/docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md
- Section: PLAN-024 — Preserve Ninja software display names
- Resume gate: Local implementation is complete. Python compilation, focused Ruff, registry validation, and `git diff --check` pass. Django/template checks and live behavior remain unverified because Django is not installed locally. Commit authorized 2026-10-27. Origin push approval must explicitly include pending migration 0354 and its automatic Portainer deployment; push origin before the required secondary mirror.
- Last checked: 2026-10-27 (Ninja spelling is wired across human-facing Operations product labels, findings, approvals/review, client/Computer views, exports, and software admin lists; canonical values remain keys).
