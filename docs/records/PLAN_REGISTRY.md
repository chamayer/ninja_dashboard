# Plan registry

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
- Status: verify
- Defined: 2026-10-08
- Started: 2026-10-08
- Completed: —
- Blueprint: —
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — source-driven collection
- Resume gate: Reconcile the October recovery checkpoint with current Jobs code, decisions, and deployed evidence.
- Last checked: 2026-10-20 (live). Six source bindings are enabled/scheduled; R-U-ON, Hudu, ScreenConnect, LogMeIn, and SentinelOne had no failed runs in seven days, while Ninja had 39 failed runs of 167.

## PLAN-003 — Central work queue and finding state

- Scope: Operations findings workflow
- Status: completed
- Defined: 2026-10-14
- Started: 2026-10-15
- Completed: 2026-10-26 (implementation complete locally; deployment pending separate approval)
- Blueprint: operations/BLUEPRINT.md
- Source: docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Active plan — Central work queue (design awaiting approval)
- Resume gate: Origin push requires separate approval; it automatically deploys and applies migrations 0352-0353. PLAN-004 identity work remains excluded.
- Last checked: 2026-10-26. W7 now suppresses a dependency only under an active exact-run/job parent, keeps its closure reason and parent key, and exposes related Job run links on Admin Health; the overlapping `operator.jobs` queue emitter closes with a reason. W8 adds a tenant-RLS, invoker-security union view and uses it for admin taxonomy counts; storage and resolution surfaces remain separate. W9 adds migration 0353 to close only exact active cross-ledger duplicates with the admin row ID and reason. `device_long_offline` is already historical, `multi_av_conflict` disabled, and source withdrawal was retired in 0316; identity-related candidates stay with PLAN-004. Python compilation, registry validation, and `git diff --check` pass. Django/database migration checks and production behavior remain unverified.

## PLAN-004 — Computer identity, history, and naming

- Scope: Operations identity lifecycle
- Status: verify
- Defined: 2026-10-16
- Started: 2026-10-16
- Completed: —
- Blueprint: —
- Source: operations/docs/archive/workspace-cleanup-2026-10-20/plan.md
- Section: Computer identity and platform change history (2026-10-16); How a Computer is named — ADR-0034 proposal (2026-10-19)
- Resume gate: Reconcile post-ADR-0034 follow-ups against the 0.128.0 release and current ADRs.
- Last checked: 2026-10-20 (live). Identity relations are present; 32 merges occurred in seven days and seven name collisions remain. This confirms activity, not completion of the follow-up plan.
- Follow-up added 2026-10-26: reconcile `client_unattached_group`, `unnamed_source_group`, and `client_link_collision` at the end of each client-resolver run when a group is assigned, inactive, or gone. Also close a collision when the group no longer matches two or more clients. Record a reason for each closure. Entity-candidate withdrawal is tracked separately under PLAN-021.

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
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: BLUEPRINT.md
- Section: Computers full-fleet inventory contract
- Resume gate: Re-measure the deployed Computers page, then design the rebuildable, existing-authority-owned inventory read model and its refresh_derived() hook; preserve tenant/RLS, filters, cards, CSV, and source/coverage/Hudu semantics. Requirement-rule changes belong to PLAN-014.
- Last checked: 2026-10-21 (prerequisite cc5d936 and page fixes 453c41c and ccae6da deployed; the read model, refresh function, re-measurement, and parity validation are not started).

## PLAN-013 — Operations sign-in page

- Scope: Operations authentication pages
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/BLUEPRINT.md
- Section: PLAN-013 — Operations sign-in page
- Resume gate: Independent of PLAN-012 (no shared files). Verify the blueprint checkpoint against the working tree before continuing.
- Last checked: 2026-10-21 (committed and pushed; deployed sign-in not yet verified).

## PLAN-014 — Requirement applicability

- Scope: Evaluator coverage rules and Computers requirement display
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: ingest/BLUEPRINT.md
- Source: ingest/BLUEPRINT.md
- Section: PLAN-014 — Requirement applicability
- Resume gate: After deployment, run platform-evaluate and compare covered counts and requirement-state drift with the measured impact; then mark complete.
- Last checked: 2026-10-21 (implemented with migration 0333 and ADR-0036; local validation passed; deployment pending).

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
- Status: active
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-019-data-pipeline-correctness-and-retention.md
- Section: PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)
- Resume gate: Executing this plan or any step requires separate explicit user approval. Coordinates with PLAN-002/005/007, which keep their own statuses and gates; F04 stays with PLAN-012.
- Last checked: 2026-10-26 (Step 1 and Step 2 (U04, migration 0349) deployed in 0.129.0; F09 decided: no daily presence; next is Step 3 with its own approval).

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
- Status: ready
- Defined: 2026-10-26
- Started: —
- Completed: —
- Blueprint: —
- Source: operations/docs/plans/PLAN-021-entity-candidate-lifecycle.md
- Section: Generic entity candidate lifecycle reconciliation
- Related plan: PLAN-004 covers client resolver findings; PLAN-021 concerns the separate generic `entity_candidates` projection and state machine.
- Resume gate: Review the measured stale candidate population and verify the 74 observed-only candidates with source links. Approve implementation separately before changing candidate state, schema, or production data. Preserve attached identity/history and rejected decisions; withdrawal must be auditable and idempotent.
- Last checked: 2026-10-26 (read-only production measurement: 576 pending and 12 observed-only candidates matched inactive observations without source links; 19 pending and 3,878 observed-only candidates matched active observations; 74 observed-only candidates had source links but were not attached. No active observation lacked either a candidate or source link. The 74 require freshness verification.)

## PLAN-022 — Legacy data and code cleanup

- Scope: Export and remove legacy tables, schemas, views, Jobs and code no current workflow reads: Ninja daily presence, legacy Ninja snapshots, agent compliance (absorbs PLAN-006) and the inventory schema; Wave B items need their own design.
- Status: active
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-022-legacy-data-cleanup.md
- Section: PLAN-022 — Legacy data and code cleanup
- Resume gate: User approved immediate execution (2026-10-26). Three separately approved pushes: migration 0349; the code; then the drop migrations 0350, 0351, 117 and 118 after the archive is copied off-host and verified.
- Last checked: 2026-10-26 (Wave A deployed: 0.129.0 and 0.129.1; database 62.4 GB → 28 GB; one five-minute Operations outage from the first 0351, fixed by 0.129.1; Wave B items need their own design and approval).

## PLAN-023 — Software installations layout repair

- Scope: Align and compact installation filters and bound long install paths within the table; template-only UI changes.
- Status: completed
- Defined: 2026-10-27
- Started: 2026-10-27
- Completed: 2026-10-27
- Blueprint: operations/BLUEPRINT.md
- Source: operations/BLUEPRINT.md
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
- Source: operations/BLUEPRINT.md
- Section: PLAN-024 — Preserve Ninja software display names
- Resume gate: Local implementation is complete. Python compilation, focused Ruff, registry validation, and `git diff --check` pass. Django/template checks and live behavior remain unverified because Django is not installed locally. Commit authorized 2026-10-27. Origin push approval must explicitly include pending migration 0354 and its automatic Portainer deployment; push origin before the required secondary mirror.
- Last checked: 2026-10-27 (Ninja spelling is wired across human-facing Operations product labels, findings, approvals/review, client/Computer views, exports, and software admin lists; canonical values remain keys).
