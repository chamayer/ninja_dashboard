# Plan registry

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
- Status: active
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/BLUEPRINT.md
- Section: PLAN-032 — Per-instance source display titles
- Related plans: PLAN-025 established the ScreenConnect source contract; PLAN-026 remains the separate source-creation UI plan. This label correction is independent of PLAN-030 bulk candidate acceptance.
- Resume gate: Local implementation is authorized. AMROSE config `source_name` is updated to `AMROSE ScreenConnect` with a named change action. Commit and `origin` push require separate approval; the push automatically deploys through Portainer, with no migration pending.
- Last checked: 2026-10-28. The Sources page view uses `source_instances.config.source_name`, and the client-mapping link retains the catalog name. Python compilation, registry validation, and scoped whitespace checks pass; tests were not run. The production GUI still runs the previous code until an approved push/deployment.

## PLAN-031 — Source record and reported states

- Scope: Distinguish source-record presence from each record's reported online state in Operations.
- Status: active
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/BLUEPRINT.md
- Section: PLAN-031 — Source record and reported states
- Related plans: PLAN-012 owns broader source-record reads and performance; this change appends one safe metadata field and preserves its existing query contract.
- Resume gate: Implement the approved view migration and page; production migration, commit, and deployment require separate authorization.


## PLAN-030 — Bulk accept discovered client candidates

- Scope: Let Operations users create new clients from a selected set of open source-client candidates in one reviewed, audited action.
- Status: active
- Defined: 2026-10-28
- Started: 2026-10-28
- Completed: —
- Blueprint: operations/BLUEPRINT.md
- Source: operations/BLUEPRINT.md
- Section: PLAN-030 — Bulk accept discovered client candidates
- Related plans: PLAN-004 retains identity matching policy; PLAN-029 surfaced the local first-ingest candidate backlog. This plan only batches the existing operator-approved accept-as-new action and does not change matching or mapping rules.
- Resume gate: Implementation is authorized. Keep the action scoped to explicitly selected open candidates; preview before acceptance; use the existing client creation, source attachment, and audit behavior. No production deployment, commit, or push is authorized.
- Last checked: 2026-10-28. Local refresh was approved; Operations now runs bulk acceptance from Inventory → Clients and Client mappings at port 3003. Migrations 0358/0359 applied to the isolated dev database; Operations, Postgres, ingest, and Jobs worker are healthy/running; login HTTP 200 and Django system check pass. No candidate acceptance or source collection ran; manual UI review is pending.

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
- Source: operations/BLUEPRINT.md
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

- Scoped repair: operations/docs/plans/PLAN-004-source-record-status.md — per-record status/contact is complete locally; scoped commit approved, push/deployment remain gated.
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
- Design: docs/plans/PLAN-014-requirement-reconciliation.md. Release `0af8aac` (0.129.3, migration 0356) is deployed per the build checkpoint. Acceptance continuation and the scoped diagnostic correction are recorded in docs/records/PLAN-014-acceptance-2026-10-27.md.
- Execution order: PLAN-014 repairs evaluator requirement reconciliation before PLAN-003 changes shared finding persistence/relationships. PLAN-003 retains that shared redesign. PLAN-012's ADR-0035 resolution-reader follow-up is handled here only for requirement finding resolution; page readers remain PLAN-012.
- Resume gate: User approved the scoped 0.129.4 commit and push, including migration 0357 and automatic origin deployment. Push origin before the mirror; do not trigger a separate redeploy. Start post-deployment acceptance in a fresh session. Production recalculation retains its own approval. Complete only after current zero-unexplained-drift evidence, preserving guarded history.
- Last checked: 2026-10-27 (read-only diagnosis and local candidate validation). Current and recorded drift agree on 109 entries; candidate summary explains 64 and leaves 45 contactless entries on 20 Computers. User approved preparing reported-state fallback. Its read-only preview qualifies all 45 and affects 102 Computers fleet-wide (62 online, 40 offline with unknown duration). Final ingest batch: 135 passed; Operations coverage/migration tests: 43 passed. Django/migration-state checks and focused Ruff pass. Candidate and migration 0357 are locally validated; production acceptance remains pending. Evidence: docs/records/PLAN-014-acceptance-2026-10-27.md.

## PLAN-015 — One-time source-record identity reconciliation

- Scope: Read-only fleet preview of which existing source records the current resolver would attach to a different Computer, then separately reviewed and approved repairs.
- Status: active
- Defined: 2026-10-21
- Started: 2026-10-21
- Completed: —
- Blueprint: —
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
- Blueprint: —
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
- Status: active
- Defined: 2026-10-26
- Started: 2026-10-26
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: docs/plans/PLAN-019-data-pipeline-correctness-and-retention.md
- Section: PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)
- Resume gate: Executing this plan or any step requires separate explicit user approval. Coordinates with PLAN-002/005/007, which keep their own statuses and gates; F04 stays with PLAN-012.
- Last checked: 2026-10-26 (Step 1 and Step 2 (U04, migration 0349) deployed in 0.129.0; F09 decided: no daily presence; next is Step 3 with its own approval).
- Received from the backlog (2026-10-28, from PLAN-022): retention for
  `ninja_activities.activities` (774k rows, 7.0 GB, live). Choose a period;
  it affects the device timeline and any activity trends. Outside the
  approved steps; needs its own approval.

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
- Status: active
- Defined: 2026-10-26
- Started: 2026-10-27
- Completed: —
- Blueprint: BLUEPRINT.md
- Source: operations/docs/plans/PLAN-021-entity-candidate-lifecycle.md
- Section: Generic entity candidate lifecycle reconciliation
- Related plan: PLAN-004 covers client resolver findings; PLAN-021 concerns the separate generic `entity_candidates` projection and state machine.
- Resume gate: Local implementation and validation are complete. A push to `origin` must be separately approved and explicitly include automatic Portainer deployment and pending migration 0355; push the same approved commit to the secondary mirror afterward.
- Last checked: 2026-10-27 (read-only verification found 77 linked, non-attached observed-only candidates; all had active observations, matching material hashes, and source-link classes that differ from the candidate's proposed class. Seventy-six observations were newer than the candidate snapshot. Review evidence is aggregate-only in `docs/records/PLAN-021-candidate-review-2026-10-27/`.)

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
