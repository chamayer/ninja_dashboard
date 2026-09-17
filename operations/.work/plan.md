# Conditions framework — full implementation and acceptance plan

## Status, goal, and how to resume

**Implementation in progress. WP3/WP4 producer evidence and lifecycle work are
the current slice; the full deliverable remains incomplete until WP3-WP8 exit
evidence exists.**
Verified baseline: `ac1f78d` on local HEAD and both remote master branches.
This replaces the contradictory handoff that called the whole feature complete
while retaining unfinished work. Checked items below mean precisely the named
component is complete; they do not certify end-to-end behavior.

Goal: one governed, evidence-based conditions framework supporting operator
issues, alerts/digests, and internal triggers/actions. All native subscribers
must agree on eligible scope without hiding retained facts or losing decisions.

Current agent: preserve the pre-existing worktree changes, continue measured
producer/lifecycle integration and subscriber validation, then complete the
live and release acceptance gates.
Do not repeat the full discovery, rewrite the working shared engine, or regard
the passing foundation tests as proof that all producers/consumers are wired.
Update each work-package checkbox only after its exit evidence exists.

## Execution instruction — continue until the full deliverable is complete

- The active assignment is the entire implementation plan, WP1 through WP8,
  not just the current slice or next checkbox.
- After completing a step or work package, record its actual validation and
  checkpoint, then immediately continue to the next unblocked step in the same
  turn. Do not end the turn merely because a step, test run, or milestone finished.
- Give brief progress updates while working. Do not ask "shall I continue?",
  offer the next approved step as optional, or wait for another "go" message.
- A validation gate requires checking the result, not another approval. Fix
  ordinary implementation/test failures within scope and continue. If one task
  is blocked, continue independent approved work where safe.
- Pause only for a material decision or question that requires user input,
  missing authority, conflicting requirements, or a genuine blocker with no
  safe in-scope workaround. State the exact question/blocker, the relevant
  evidence, and the recommended next action. Do not manufacture questions for
  routine implementation choices already covered by this plan.
- Continue to honor all permission, migration-review, validation, and safety
  boundaries below. Persistence does not authorize new scope or a manual redeploy.
- End with a final completion response only when the full deliverable and its
  required acceptance checks are complete, or when one of the pause conditions
  above genuinely requires handing control back to the user. Keep unfinished
  items explicitly open; never mark them complete just to end a turn.

## Scope and authority

- The original planning/audit turn changed documentation only. That historical
  restriction does not limit the subsequently authorized implementation to
  planning or require a pause between work packages.
- Existing user approval covers reviewed migrations and commit/push once the
  implementation is ready. Review the exact Django AND ingest pending sets.
- **No manual redeploy.** Automatic deployment on origin push may run migrations.
  This user instruction overrides the repository's coupled-redeploy instruction.
- Push an approved release to origin, then a-m-rose; report the short hash.
  Do not push plan-only changes to trigger deployment.
- No manual production migrations, data rebuilds, automatic merges, live source
  mutations as tests, or destructive status backfill without separate authority.
- Keep testing focused, but PostgreSQL/RLS and external-action safety cannot be
  established with static assertions or mocked tests alone.
- Database policy authority and governed admin version management are required.
  Preserve the latest handoff's requirement for admin draft/review/activation;
  this is not advanced backlog work. General-purpose arbitrary rule scripting
  and unrelated advanced issue columns remain out of scope.
- Preserve uncommitted `.work/backlog.md`, existing identity-review edits in
  `operations/templates/device_detail.html`, and all `.work/probe_*` /
  bootstrap artifacts. Inspect/stage only task-owned hunks.
- Use existing dependencies, permissions, audit and queue patterns. Escalate a
  genuinely new permission/scope decision rather than assuming authority.
- Root VERSION/CHANGELOG remain release authorities. ADR-0012 governs owned
  entities versus global software, evidence versus selected state, and mapping
  authority. Read ADR-0021 before changing the condition policy architecture.

## Verified progress — preserve this work

| ID | Status | Component and evidence |
| --- | --- | --- |
| C1 | [x] Complete | Shadow foundation: `5922c87`; command, bounded read-only reader/report, 53-definition profile, pure contracts/tests |
| C2 | [x] Complete | Shared pure implementation in `shared/conditions/{contracts,engine,policy}.py`; Operations files now compatibility imports, not duplicated engines |
| C3 | [x] Complete | Both Dockerfiles COPY `shared/`; Operations also packages its migrations. Build/runtime verification remains a release gate |
| C4 | [x] Complete | Initial additive schema/seed exists in `0161_live_condition_contract.py`: policy versions/definitions, assessments, participants, RLS and read view |
| C5 | [x] Complete | Operations and ingest live adapters load database policy; packaged profile is shadow/bootstrap input. `ac1f78d` fixes JSONB text decoding; regression passes |
| C6 | [x] Complete | Code for policy-version creation/activation and audit exists in Django admin; complete governance/security workflow is still partial (WP2) |
| C7 | [x] Complete | Issues/Admin Health display stored assessment or pending state; this is presentation plumbing, not verified current eligibility (WP6) |
| C8 | [x] Complete | Commits `aa4ef58`, `502306a`, `ac1f78d` exist; both remotes verified at `ac1f78dc206aa17e24c7d81fb61ac390a49a7ed2` |
| C9 | Partial | Several producers persist assessments and several readers check them, but readiness assumptions, missing paths and lifecycle semantics are incorrect/incomplete |
| C10 | Not verified here | Earlier plan reports automatic migration 0161, health and Issues HTTP 200. No production connection was made in this audit; do not restate as newly verified |
| C11 | Incomplete | VERSION is still 0.123.0 and changelog describes shadow-only behavior; the live commits have no corresponding release entry |

The earlier standalone SQL draft is gone. Do not recreate it or edit migration
0161 to change already-shipped schema behavior. Use the next available additive
migration number after rechecking HEAD. The schema is implemented, but its
hardening, rollback, participant validity and currentness semantics are not done.

## Validation performed in this audit

- Git status, commit diff `5922c87..ac1f78d`, targeted code paths and both
  remote branch heads inspected.
- **40 passed**:
  `apps/core/tests/test_conditions.py`,
  `test_conditions_command.py`, `test_conditions_live.py`.
- **Django system check passed**, no issues.
- Workstation prerequisite: from `operations/`, put both repository root and
  Operations on PYTHONPATH. Initial test invocation without root failed with
  `ModuleNotFoundError: shared`; adding root made the same tests pass.
- These ran with local Python 3.14; production is Python 3.12. No PostgreSQL,
  image build, browser, ingest end-to-end or production verification rerun here.
- Existing PostgreSQL file `ingest/tests/test_condition_policy_postgres.py`
  contains three schema/role/policy tests. Their existence is verified; prior
  passing counts are historical reports, not this audit's execution.
- Documentation whitespace validation is recorded at the final checkpoint.

## Full deliverable — non-negotiable behavior

1. Keep distinct axes: observed condition/evidence; handling (acknowledged,
   investigating, snoozed, suppressed, resolved); readiness; response eligibility.
   Retained evidence is never silently deleted because it is irrelevant now.
2. Unsettled computer identity blocks dependent COMPUTER attribution and actions.
   Identity repair remains available; no self-blocking dependency cycles.
3. Extended offline state may suppress routine attention, not prove a fix.
   Current bootstrap threshold is 180 days. Independent security/identity
   findings are not suppressed simply because they have lower severity.
4. Negative evidence/clearing requires successful, complete, fresh evaluation of
   the exact required scopes. Empty output, skipped evaluation, missing history,
   partial pagination or unrelated successful snapshots are not success.
5. Support multiple typed participants and explicit relationships/roles.
   Clients and linked entities are subjects too. Global software is reference
   data, not a tenant-owned Operations entity; an installation is a relationship.
6. Scope decisions individually and, when declared, jointly. Context-only
   participants must not accidentally require their own actionable assessment.
   One blocked exposure cannot erase an independent global software fact.
7. Preserve finding IDs, meaningful condition keys, history, action references,
   operator choices, and active episodes across refresh/merge. Do not recreate
   a new open row just because the previous row is investigating/suppressed.
8. Eligibility never grants permission. Retain source target verification,
   confirmation, authorization, lease/idempotency, approval and routing checks.
9. Reevaluate when inputs, membership, identity, handling or policy change.
   Dependency recovery/snooze expiry alone cannot revive an obsolete finding.
10. Operators can find ALL retained issues, with understandable reasons and
    repair links. Category/type mapping is complete, governed and human-readable.
11. Admins can create, validate, compare and explicitly activate policy versions
    with authorization and audit, without code deployment.
12. All native findings subscribers must be classified and connected; external
    raw SQL/history compatibility must be documented rather than silently changed.

## Confirmed defects and their implementation targets

| Defect verified in current code | Target / work package |
| --- | --- |
| Notifications and digest explicitly permit rows with NO assessment | `ingest/notifications.py:_load_pending_findings`, `notifications_digest.py:send_digest`; WP5 |
| Admin half of notification UNION has no assessment gate | Same notification loader; WP5 |
| SQL policy comparisons can become NULL when active policy is absent; policy presence is not consistently required | Shared validity predicate, readers and clear guards; WP2/WP5 |
| Patch and Windows producers hardcode identity READY; patch also hardcodes online READY; Hudu hardcodes collection READY | `patch_findings.py:_record_assessment`, `intel/windows_servicing.py:_record_assessment`, `cmdb_findings.py:_record_stale_assessment`; WP3/WP4 |
| Many producers set `EvaluationCoverage(True, True, True, True)` without measured scope proof | Ingest emitters; WP3/WP4 |
| Coverage evaluator reports non-conflicting identity UNKNOWN and collection UNKNOWN without a path to proven readiness | `evaluator.py:_device_condition_signals`; WP3 |
| Many producers build Condition with status open and no stored snooze, ignoring actual handling | Emitter adapters; WP4 |
| Patch clearing permits no-assessment rows and relies on prior positive assessments rather than a current negative evaluation | `patch_findings.py:_auto_resolve`; WP4 |
| Other clearing helpers check only existence of a may_clear row; several paths remain unchanged | Evaluator, CMDB, software, Windows, client resolver; WP4 |
| Constant reevaluation keys such as patch/software/cmdb + condition_key do not identify changing input evidence | All adapters and persistence; WP3/WP4 |
| Each participant assessment deletes/reinserts the whole participant set; removed participant assessments are not reconciled | Both `record_assessment` adapters; WP2/WP4 |
| Hudu passes source_instance_id under participant kind source_binding | CMDB adapter; WP3/WP4 |
| Identity producer includes a context client but assesses devices only; notification completeness gate requires every participant | Resolver and subscriber aggregation; WP3/WP5 |
| Worker checks saved flags/version/age but not fresh dependency/handling state or all required participant scopes | `source_actions.py:_still_eligible`; WP5 |
| Source-action POST/retirement paths, client resolver, exposure SQL, navigation and client-workspace were not integrated by these commits | WP4/WP5/WP6 |
| Assessment display unions stored responses without active-policy/currentness checks | `views.py:_condition_assessment_display`; WP6 |
| No response filter; actionable counts still derive from raw status/type; offline coalescing explicitly hides some rows | `views.py:findings_queue`, templates; WP6 |
| UI uses legacy issue_categories + one duplicate alias, not all per-definition category/type/label mappings | `shared/conditions/profile.json`, `views.py:_issue_taxonomy`; WP6 |
| Policy admin has raw JSON creation/action activation, no diff/confirmation/user reason workflow; activation and custom audit not explicitly one transaction | `admin.py:ConditionPolicyVersionAdmin`; WP2 |
| DB create/activate functions do not enforce the full shared parser/digest contract; global policy is writable via app functions | Migration 0161 functions; WP2 security review |
| Assessments store policy version but not a digest/FK or exact evidence/scopes; typed IDs have no referenced-subject tenant validity enforcement | Migration 0161 and adapters; WP2 |
| Migration reverse drops the trigger function before its dependent triggers/tables | New migration/rollback test and documented recovery; WP2/WP8 |
| Release docs still describe the foundation as shadow-only; release/version reconciliation remains pending | WP8 |

These are code findings, not claims about how many live customers/alerts were
affected. Do not perform customer-data dumps to substantiate the plan.

## Target contracts and dependency map

Preserve one pure rule engine. Add shared validated data contracts and use
service-specific SQL adapters, not a second rule engine in templates or SQL.

| Contract | Required contents / invariant |
| --- | --- |
| Policy selection | immutable version + digest + validated complete registry coverage; explicit active selection read consistently within assessment transaction |
| Condition episode | legacy row kind/ID/key, actual handling and snooze, truth/detection timestamps; no new row on refresh of an operator-handled active episode |
| Participant | kind, real reference, role, visibility tenant, subject/context/exposure relationship; same-tenant existence checks for owned targets |
| Required scope | producer/domain, source instance AND binding where applicable, snapshot scope, client/device/installation scope, required/optional semantics |
| Evaluation | run ID, actual input watermarks/digests, required scope set, per-scope outcomes, start/end, freshness/clock limits and negative-result coverage |
| Assessment | episode + participant/composite scope, policy version/digest, input/membership/handling versions, disposition/reason/blocker references, valid-until, may_evaluate/notify/execute/clear |
| Effective response | exact required assessments present, current policy and inputs, actual current handling, no missing/invalid/stale prerequisites; unknown fails closed |
| Transition | invalidation/reevaluation on source completion/failure, identity/merge/remap, inventory membership, approval, handling, policy activation and threshold/TTL expiry |

Dependency order:
source/configuration readiness -> scoped evidence -> identity/attribution ->
domain condition evaluation -> participant response -> operator/alert/action.
Offline affects declared relevance rules, not truth. Policy approval or scoped
software authorization affects the appropriate exposure/response, not global
catalog facts. Do not introduce an arbitrary SQL/expression rules language.

Composite scope rules must be declared data: which roles require all members,
which allow independently eligible members, and which are context only.
For example, a client patch rollup can retain all affected devices while its
actionable count includes only eligible device assessments; partial exposure
does not license an all-devices bulk action.

## Implementation work packages

### WP1 — Regression baseline and consumer/writer inventory

Status: [x] Complete locally. Dependency: verified baseline above.

Files: existing conditions tests, ingest focused tests, this plan.
- [x] Add small failing regressions for hardcoded identity readiness, unknown
  collection treated as ready, no-assessment notification, offline auto-clear,
  ignored snooze, context-only participant gating and stale policy selection.
  Coverage: `test_identity_blocks_all_responses_but_does_not_clear_condition`,
  `test_collection_missing_scope_is_unknown_even_when_other_snapshots_succeed`,
  `test_notifications_require_current_assessment_for_entity_and_admin`,
  `test_evaluator_lifecycle_absent_closure_requires_current_clear_assessment`,
  `test_snooze_is_preserved_and_expiry_does_not_bypass_prerequisites`,
  `test_context_participant_is_not_an_action_scope_and_all_members_must_pass`,
  and `test_active_policy_reader_requires_current_active_policy_and_digest`.
- [x] Search ALL Finding/AdminFinding INSERT/UPDATE/ORM writes and all readers,
  including resolver helpers, scheduled tasks, APIs/serializers, dashboards and
  action endpoints. Extend the matrix below for any additional native subscriber.
  Inventory recorded below; historical migrations are schema/backfill code,
  and `ninja_agent_compliance` is a documented external raw-evidence boundary.
- [x] Record each writer's finding types, physical row kind, subjects, scope,
  upsert/clear function and assessment status. Validate registry names against
  the actual DB during approved read-only release checks.
  The detailed writer matrix above is complete; the disposable PostgreSQL
  registry check passes 3 tests. Production registry comparison remains a
  WP7/WP8 release gate and is not inferred from local files.
- [x] Keep red tests localized; do not rewrite unrelated tests or broaden scope.
  Final audit found test edits limited to conditions/safety, policy-reader,
  queue, and directly affected producer contract coverage.

Exit: every writer/consumer is classified, each confirmed safety defect has a
small regression, and there is an explicit before/after acceptance target.
Acceptance target: before this work, missing/invalid/stale assessment paths
could be treated as eligible or could clear/notify without current evidence;
after this work, the seven localized regressions fail on those unsafe
behaviors, current policy/handling/participant gates are explicit, and the
writer/consumer matrix records each native boundary. Baseline validation passes
62 Operations tests and 22 ingest safety/evidence tests; the disposable
PostgreSQL registry suite passes 3 tests. Production registry comparison and
live behavior remain outside this local WP1 closure.

#### WP1 item 2 inventory

| Boundary | Native writer/reader locations | Classification |
| --- | --- | --- |
| Evaluator | `ingest/evaluator.py` writes entity and admin findings and lifecycle clears; `ingest/identity/resolver.py` writes identity findings and closes stale conflicts | Native writers; assessments are recorded on governed paths, with lifecycle/identity closure guards |
| Identity/client resolution | `ingest/identity/client_resolver.py` writes client findings and admin findings; resolves admin rows after a current resolver assessment | Native writer; entity/admin row kinds are explicit |
| CMDB/Hudu | `ingest/cmdb_findings.py` writes source-scoped entity findings and clears absent rows | Native writer; source instance/binding participants and complete-snapshot evidence |
| Patch and servicing | `ingest/patch_findings.py` and `ingest/intel/windows_servicing.py` write entity findings and clear absent rows | Native writers; current assessments required; patch/offline coverage remains fail-closed |
| Software | `ingest/software_findings.py` writes device, product, version, and installation findings and clears absent rows | Native writer; participant assessments recorded; software run-freshness decision remains open |
| Platform health | `ingest/platform_findings.py` writes source-failure and queue-stall admin findings and resolves absent admin rows | Native writer; admin row kind and synthetic `platform_signal` participant are explicit |
| Alerts and actions | `ingest/notifications.py`, `ingest/notifications_digest.py`, and `ingest/source_actions.py` read findings/assessments and recheck before send or mutation | Native subscribers; current policy, handling, participant, and freshness gates |
| Operations UI/read models | `operations/apps/core/conditions/reader.py`, `client_workspace.py`, `context_processors.py`, and `views.py` read findings, assessments, counts, exports, queue/admin/device/client surfaces | Native subscribers; effective response is used for actionable semantics and raw evidence remains available |
| Other reporting | `ingest/parity_check.py`, Operations CSV/report paths, and dashboard/bootstrap readers | Read-only/reporting subscribers; raw versus effective semantics are preserved or explicitly labeled |
| External compatibility | `ninja_agent_compliance` tables, SQL views, and ingest workflows | Legacy/external evidence boundary; not an Operations Finding/AdminFinding writer and not silently repointed |

#### WP1 item 3 writer matrix

| Writer | Finding types | Physical row / subject scope | Upsert and clear path | Assessment status |
| --- | --- | --- | --- | --- |
| `ingest/evaluator.py` | `source_failure`, `unmapped_node_class`, `duplicate_platform_record`; `device_role_conflict`, `lifecycle_unknown_reported_state`, `lifecycle_reported_state_conflict`, `missing_required_platform`, `stale_required_platform`, `device_unenrolled`, `device_source_record_withdrawn`, `device_missing_from_source`, `device_offline`, `device_stale_data` | Admin rows use deterministic condition keys; entity rows use client/device subjects; coverage and lifecycle rows are device-scoped | `_upsert_admin_finding` / `_upsert_finding`; lifecycle and type-specific `_resolve_*` helpers | Admin and assessed entity paths are recorded; lifecycle/data-quality follow-up remains identified in WP4 |
| `ingest/identity/resolver.py` | `identity_conflict`, `shared_serial`, `cross_client_serial`, `placeholder_serial`, `placeholder_mac`, `unmatched_source_group` | Entity rows are device-scoped except source-group rows, which retain source-binding references and source details | SQL upserts in resolver; identity-conflict close is assessment-guarded; other data-quality cleanup remains explicit follow-up | `identity_conflict` has participant assessments; remaining data-quality writers are evidence-only pending WP4 integration |
| `ingest/identity/client_resolver.py` | `unnamed_source_group`, `client_link_collision`, `client_unattached_group`, `client_name_conflict` | Entity rows use client/source subjects; admin rows use source-group/link references and current source-binding participants | `_emit_finding`, `_emit_unnamed_source_group_finding`, `_resolve_finding` | Admin resolver findings are assessed and clear-guarded; unnamed/entity paths remain documented WP4 follow-up where no assessment is written |
| `ingest/cmdb_findings.py` | `cmdb_asset_stale`, `cmdb_link_incorrect`, `duplicate_device_records`, `unintegrated_source_observed` | Source-instance/source-binding or client/device entity subjects; Hudu target IDs remain in finding details | `_upsert` and `_resolve_absent`; stale rows use `_record_stale_assessment` with source instance/binding participants | Stale archive path has measured complete-snapshot assessment; other Hudu evidence paths remain evidence-only or pending integration |
| `ingest/patch_findings.py` | `device_never_patched`, `patching_stalled`, `reboot_pending`, `patch_failing_repeatedly`, `patch_approval_backlog` | Device or client entity subjects according to finding scope; patch/source keys remain stable | `_emit`/upsert SQL and `_auto_resolve` | Participant assessments are written; identity/contact/coverage is deliberately unknown and clearing is fail-closed |
| `ingest/software_findings.py` | `suspicious_name`, `install_path_suspicious`, `unauthorized_av`, `unauthorized_rmm`, `unauthorized_remote_access`, `multi_av_conflict`, `rare_recent`, `eol_runtime`, `whitelist_suggestion`, `vulnerable_software`, `known_malicious_hint`, `capability_review_candidate` | Device, software product, software version, or software installation subjects; installation/device participants preserve exposure relationships | `_emit_scoped`; `_auto_resolve` | Participant assessments are written; device identity is measured, while software run freshness and complete clearing evidence remain WP3 follow-up |
| `ingest/intel/windows_servicing.py` | `windows_servicing_eol`, `windows_servicing_approaching_eol`, `windows_servicing_unknown` | Device entity subjects | `_sync_findings` upsert and absent-device clear | Device participant assessment uses shared measured identity; complete clearing coverage remains fail-closed |
| `ingest/platform_findings.py` | `source_failure`, `software_queue_stalled` | Admin rows use deterministic synthetic platform subjects; assessment participant kind is `platform_signal` | `_upsert`; `_resolve_admin_absent` | Admin assessments use `row_kind='admin'`; queue/source evidence is measured per current run and clear-guarded |

### WP2 — Harden policy authority and durable state

Status: [x] Complete locally. Production/RLS/concurrency release validation remains a WP7/WP8 gate. Dependency: WP1.

Files: shared contracts/parser, both live adapters, new additive Operations
migration, models/admin/forms/templates, ADR-0021.
- [x] Retain DB as sole live policy authority. Load one validated version/digest
  per transaction/batch; absent, invalid or registry-incomplete selection fails
  closed. Never silently fall back to packaged JSON.
- [x] Version validation includes every registered type exactly once, valid
  groups/labels/aliases, known rules/effects/scopes/providers, no cycles,
  positive thresholds, supported schema, version/document agreement and digest.
  Reject duplicate members and references to nonexistent types.
- [x] Make validity/activation an enforceable boundary, not merely an admin UI
  convention. A runtime caller of a granted SQL function must not activate
  arbitrary unvalidated JSON or choose its own unchecked digest.
- [x] Govern draft -> validation -> diff review -> explicit activation.
  Capture user-supplied reason, actor, timestamp, old/new version/digest and
  validation result. Activation + audit + active selector change are atomic;
  serialize concurrent activations. Invalid drafts leave prior policy active.
- [x] Define global-policy administration explicitly: a tenant-scoped taxonomy
  permission must not silently grant cross-tenant global policy changes. Follow
  platform-admin conventions; separate tenant override scope if required.
- [x] Preserve immutable versions; allow safe reactivation of a known valid
  earlier version with audit, without modifying it or rewriting assessments.
- [x] Add policy digest/reference and evidence/scope/membership/handling
  currentness metadata to assessments. Validate participant type/ID and owned
  target tenant; preserve global software references without assigned ownership.
- [x] Replace per-participant DELETE/reinsert with one atomic batch for a
  condition's participant set/assessments. Lock/version the parent, reconcile
  removed scopes, preserve auditable transitions, and reject late stale writes.
- [x] Keep current projection bounded and retain material decision changes,
  rather than generating history for unchanged heartbeats. Define retention.
- [x] Test RLS with runtime roles, cross-tenant forged references, missing tenant
  context, function privileges, denied view DML and concurrent policy activation.
  Review rollback dependencies; do not drop a function while triggers depend on it.
- [x] Treat shipped 0161/profile checksum as immutable deployment history.
  Any bootstrap seed relocation must preserve exact original bytes/digest and
  new-install reproducibility; live policy updates go through governed versions.

Exit: invalid policy/forged participant cannot enter an authoritative response;
admins can safely manage versions; both services share identical engine inputs.

### WP3 — Implement measured readiness, coverage and invalidation

Status: [x] Complete locally. Production-scale query-plan and live invalidation validation remain release-gated. Dependency: WP2 contracts.

Files: proposed shared evidence contracts, ingest signal reader(s), Operations
read/action adapter, existing identity/observation/queue integration points.
- [x] Batch-load identity evidence for all affected devices. Require known client,
  valid source attachment through device.entity_id and unresolved-ambiguity
  checks. Use authoritative merge/resolver evidence, not only finding absence.
  Missing/contradictory evidence is unknown; unresolved ambiguity is blocked.
- [x] Keep repair conditions independent. Add an audited reviewed-distinct
  decision only in the existing review workflow, scoped to exact membership/
  evidence fingerprint; invalidate it when relevant evidence changes.
- [x] Derive offline readiness from relevant agent contact timestamps and policy.
  Detect missing/future/contradictory contact; distinguish retired, withdrawn,
  online-but-stale and genuinely extended offline states. Do not blanket
  suppress vulnerabilities or use source-reported online as identity proof.
- [x] Producers declare ALL required source scopes before evaluation. Read
  observation_snapshot_runs using status=complete, complete-snapshot flag,
  expected/written/failed counts, time bounds and exact scope/run identity.
  Cover source outages, pagination/truncation, deleted bindings and empty scopes.
- [x] Provide equivalent explicit run evidence for non-snapshot domains such as
  software intelligence and queue health. Do not force those into fake computer
  or source-binding participants.
- [x] Preserve Hudu's client subject and exact source-record reference; use
  correct source_instance versus source_binding IDs. Validate linked-source
  absence across required sources; current Hudu row alone is not that proof.
- [x] Generate reevaluation keys from real evidence/policy/membership watermarks,
  not condition_key alone or wall-clock execution alone.
- [x] Invalidate responses on merge/remap, source failure/new snapshots,
  participant/installation change, handling/approval change and policy activation.
  Schedule bounded re-evaluation of affected current episodes. Expiry must be
  enforced at consumption even if no scheduler cycle has run.
- [x] Batch reads and transaction-scoped policy caching; avoid one inventory/
  policy scan per finding. Measure representative query plans on synthetic data.

Exit: known-ready, blocked and unknown cases have evidence-backed signals, and
a dependency change cannot leave a previously eligible action usable.

### WP4 — Complete producers, episode preservation and clearing

Status: [ ] Partial. Dependency: WP2-WP3.

| Writer family | Scope / current integration | Remaining work |
| --- | --- | --- |
| evaluator.py | coverage/offline hooks only on selected paths | wire lifecycle, role, unknown, unenrolled, stale-data and admin source-failure paths; fix missing-history guard; all clear helpers |
| identity/resolver.py | identity group assessments | other identity findings, same-tenant members, context roles, settled-group closure and merge invalidation |
| identity/client_resolver.py | no new assessment integration | client/source organization entity AND admin findings and resolution paths |
| cmdb_findings.py | archive helper with asserted collection READY | measured required source scopes, correct source reference, all Hudu types and negative-evaluation closure |
| patch_findings.py | write/clear hooks with asserted readiness | actual identity/contact, client rollups, partial runs, zero-output/offline distinction |
| software_findings.py | participant assessments on emitted rows | real installation/global exposure scope, approvals, measured intel/inventory freshness, guarded auto-resolve |
| intel/windows_servicing.py | identity asserted READY | shared measured identity, correct support inputs/coverage and negative-evaluation closure |
| platform_findings.py | source/queue assessments | correct typed system subjects, current handling, measured queue/source evidence and recovery |
| Other discovered writers | identify with WP1 search | explicit assessment integration or justified evidence-only classification; no silent omission |

- [x] Read actual row status, snooze and operator decisions after upsert; preserve
active investigating/suppressed episodes instead of duplicating/reopening.
Review existing duplicates before any unique-index widening.

WP4 item 2 is complete locally through the shared conditions engine and its
producer assessments. Prerequisites are evaluated before dependent responses;
blocked or unknown prerequisites produce retained evidence with no notify or
execute authority, while independent participant scopes remain evaluable.
Existing Operations condition regressions cover blocked identity, independent
software scopes, and unknown recovery behavior.
- [x] Assess prerequisites before attributing dependent conclusions. Retain
  source evidence and prior findings when evaluation is blocked; do not present
  guessed attribution as freshly confirmed truth.
- [x] Every automatic resolution uses CURRENT successful complete negative
  evaluation for that episode/scope. Prior positive may_clear is not proof of
  recovery. All missing-assessment bypasses must go.
- [x] Separate may_clear from notification/source-mutation permission: an
  operator snooze must not masquerade as truth, nor authorize stale closure.
  Define proven recovery behavior for snoozed/suppressed findings explicitly.
- [x] No blanket zero-output clearing. Conversely, a verified complete empty
  result can resolve matching scoped findings; do not permanently preserve them.
- [x] Retired, deleted, merged, policy-exempt or no-longer-applicable cases get
  explicit reason/history semantics, not a false "fixed" conclusion.
- [x] Preserve source-action IDs/legacy keys and reconcile participants after
  merge before allowing downstream responses.

Exit: all writer rows in the inventory have a tested assessment/clear policy;
skips/outages/offline never close findings; genuine recovery still closes them.

### WP5 — One effective response for every subscriber

Status: [ ] Blocker remediation complete locally; deployment validation pending. Dependency: WP2-WP4.

Implement one shared validity/selection contract, optionally an indexed SQL read
projection plus engine-produced assessments. SQL only validates currentness/
scope/flags; do not implement a second dependency rule engine in queries.

Default: unassessed/missing/invalid/stale response is **unknown, not eligible**.
Show it as pending in UI and enqueue reevaluation where appropriate, never use
"no assessment means legacy permission." Require all ACTION-required scopes,
not all arbitrary context participants. A single eligible scope is not enough
for a combined action.

#### WP5 step 1 — native subscriber inventory

| Subscriber | Verified entry points |
| --- | --- |
| Notifications | `ingest/notifications.py:dispatch`, `_load_pending_findings`, `_still_notifyable` |
| Digest | `ingest/notifications_digest.py:send_digest` |
| Source-action queue/worker | `operations/apps/core/views.py:_queue_selected_hudu_archives`; `ingest/source_actions.py:process_pending`, `_still_eligible` |
| Retirement and merge/mapping | `operations/apps/core/views.py:_retire_selected_computers`, `device_merge`, `merge_candidate_group_review`, client-candidate mapping/attachment handlers |
| Software exposure | `operations/apps/core/views.py:org_software_devices`, `software_clients`; `ingest/software_findings.py` assessment/clear paths |
| Issues/Admin Health | `operations/apps/core/views.py:findings_queue`, `findings_admin_health`, finding action handlers |
| Device/client/software/patch pages | `operations/apps/core/views.py:device_detail`, `org_devices`, `devices_page`, `patching_queue`, `software_clients`, `client_workspace.py:build_client_workspace` |
| Navigation/dashboard/client workspace | `operations/apps/core/context_processors.py`, `views.py:home`, `build_client_directory`, `build_client_workspace` |
| Health history | `operations/apps/core/views.py:sources_status`, `home`, `findings_admin_health`; retained finding and assessment readers |
| API/CSV/search/report | `operations/apps/core/views.py:search`, `findings_queue` CSV path, `conditions/report.py:build_report` |
| Metabase/reporting | `ingest/metabase_bootstrap.py`, `ingest/parity_check.py` |
| Legacy/external compatibility | `ninja_agent_compliance` tables/workflows and their SQL/report readers |

This inventories subscriber boundaries; it is not completion evidence for
their response semantics. Each row must be validated in the remaining steps.

#### WP5 step 2 — scope and flag contract

The shared contract uses these rules for every native subscriber:

| Contract element | Required meaning |
| --- | --- |
| `may_notify` | Current active-policy assessment permits attention for the finding and every non-context participant required by the notification scope. It never authorizes clearing or source mutation. |
| `may_execute` | Current active-policy assessment permits an internal/source action for every ACTION-required participant. A context-only participant identifies scope but is not an action requirement. Existing permissions, confirmations, leases, and exact-target checks remain mandatory. |
| `may_clear` | Current active-policy assessment plus successful, complete, fresh, in-scope negative/recovery coverage permits automatic closure. It never authorizes notification or source mutation. |
| Participant completeness | Missing, stale, blocked, or unknown assessment for any ACTION-required participant makes the combined action non-actionable. Independent global/software scopes may remain eligible when their own required scope is complete. |
| Handling | `open`/`acknowledged` are routine response states. `investigating`/`suppressed`, active snooze, resolved history, and operator decisions remain retained evidence and cannot become authority through stale assessments. |
| Policy authority | The assessment must match the single active policy version and freshness window. No NULL, missing-policy, or legacy-permission fallback is allowed. |

| Subscriber | Required scope/flag mapping |
| --- | --- |
| Notifications and digest | `may_notify` for the condition plus every non-context participant; current status/snooze/suppression/routing/cooldown checks remain separate. |
| Source-action queue and worker | `may_execute` for the condition plus every action participant, current handling/policy, and exact source target; queue and worker both recheck. |
| Retirement and merge/mapping | Human permission and explicit confirmation are authoritative; condition assessments may constrain eligible repair findings, but `may_execute` is not merge authorization. Merge reconciliation must complete before downstream responses. |
| Software exposure | Per-device `may_execute`/effective response for device-scoped exposure; global software facts remain visible and do not inherit a blocked device's state. |
| Issues/Admin Health and detail pages | Use effective response for actionable filters/counts; retain all findings and expose disposition/reasons/scope for non-actionable rows. |
| Navigation/dashboard/client workspace | Count only explicitly eligible `may_execute` work, or label retained/pending counts as such; never use raw finding counts as actionable. |
| Health history | Read retained historical evidence; any eligible measure is separately named and uses current response validity. |
| API/CSV/search/report/Metabase | Preserve raw evidence fields and expose effective response wherever actionable semantics are claimed; do not infer authority from raw presence. |
| Legacy/external compatibility | Remain a raw/evidence boundary unless explicitly mapped; preserve legacy tables and interfaces without silently granting Operations response authority. |

Step 2 defines the acceptance contract; the remaining steps must provide tests
and runtime evidence for each mapping.

| Consumer | Required completion / validation |
| --- | --- |
| Notifications entity + admin | same eligibility; handle no active policy safely; actual snooze/status; revalidate before send; preserve suppression rules/routing/cooldowns/fingerprints |
| Digest | same eligible scope and handling as alerts; no independent permissive SQL; bounded list/count semantics clear |
| Source action POST/queue | server-side eligibility plus existing permissions/reason/confirmation/exact source target; disabled button is not enforcement |
| Source action worker | fresh dependencies, handling and all required scopes immediately before API; changed target cancels; preserve leases/idempotency and evidence refresh |
| Bulk retire and merge/mapping | retirement checked per affected computer; repair actions remain available; never infer merge authorization from eligibility |
| Software exposure view | device-specific assessment joined to existing inventory/approval predicates; retain global fact and eligible other installations |
| Issues/Admin Health | retain all evidence; same effective disposition for rows, filtering, counts and exports |
| Device/client/software/patch pages | consistent direct and inherited issues, eligible counts and blocker links |
| Navigation/dashboard/client workspace | count explicitly eligible work or explicitly labeled retained findings; no raw-count "actionable" label |
| Health history | retain historical meaning; add a separately named eligible measure if needed, no silent rewrite/backfill |
| API/CSV/search/report/Metabase | inventory actual callers; expose effective response where actionable semantics are promised; document raw evidence endpoints |
| Legacy/external SQL | preserve tables/interfaces; document raw versus effective contract and known unmanaged subscribers; do not repoint legacy Agent Compliance silently |

- [x] Test mixed participants: independent global software + one blocked and
  one eligible device; client context-only member; all-members action.
- [x] Test source/identity/policy/snooze change after queue/selection and before
  execution. Avoid network calls under long DB locks; define final bounded
  recheck and cancellation semantics, not a claim of distributed atomicity.
- [x] Policy activation invalidates old assessments atomically; no NULL SQL
  comparison or permissive exception handler may restore eligibility.

Exit: every native subscriber is mapped; pending/blocked findings cannot alert
or mutate; independent eligible scope still functions.

WP5 item 1 is complete locally. Added a mixed-participant regression covering
an independent global software participant, blocked and eligible device
scopes, and a client context-only participant; all-members action semantics
remain fail-closed for the blocked device while eligible scopes continue to
work. The full Operations Conditions test module passes 34 tests.

WP5 item 2 is complete locally. The source-action worker performs its final
bounded eligibility check after claiming a request and immediately before the
external mutation, outside the database transaction. That check revalidates
finding handling, snooze state, current active policy/freshness, identity and
all required participant execution responses, plus the exact current source
target; any change cancels the request. Focused source-action regressions and
the full ingest safety-contract set pass (23 tests).

WP5 item 3 is complete locally. The governed policy activation function now
retains older assessment rows for explanation but atomically clears their
may_evaluate, may_notify, may_execute, and may_clear authority and records the
invalidation reason and newly activated policy. Runtime consumers still require
the active policy/version, with no NULL fallback. Focused regression and the
disposable PostgreSQL policy suite pass (3 tests).

WP5 step 3 is complete locally. Added reusable effective-response fixtures
covering eligible, blocked, pending, stale, suppressed, snoozed, and
missing-policy states, with explicit fail-closed expectations for notification,
execution, and clearing authority. The full Operations Conditions test module
passes 35 tests.

WP5 step 4 is complete locally. Added a fixture-driven subscriber matrix for
all 12 inventoried native boundaries across eligible, blocked, pending, stale,
suppressed, snoozed, and missing-policy states. Non-eligible states are
explicitly denied notification, execution, and clearing authority while
retained evidence remains available. The full Operations Conditions module
passes 47 tests. Per-subscriber runtime and production-scale validation remain
open acceptance gates.

WP5 step 5 is complete locally. Added an executable source-action transition
test proving that a failed final eligibility recheck cancels the request and
never calls the external mutation. The existing recheck contract covers
identity, source, policy, and snooze transitions. The full safety-contract
suite passes 24 tests with one skip because the local environment lacks the
optional `httpx` connector dependency.

WP5 step 6 is complete locally. The disposable PostgreSQL suite now exercises
tenant-scoped RLS reads, atomic authority invalidation during policy
activation, stale participant/assessment reconciliation, and transaction
advisory-lock serialization. The suite passes 5 tests; the safety-contract
suite passes 24 tests with one optional `httpx`-dependent skip. Live
production-role and deployment validation remain release-gated.

WP5-WP8 release checkpoint: commit `360ee2b` was pushed to `origin` and the
secondary mirror. Automatic rollout completed; Operations is healthy and
reports migrations 0162-0168 applied. Runtime-role checks show tenant 1
assessment visibility and zero tenant 2 visibility through the current view;
the assessment base table is readable by the ingest writer role while the
current view is not writable. Focused Operations tests pass 159 with two
PostgreSQL opt-in skips, the disposable condition-policy suite passes 5,
the safety-contract suite passes 24 with one optional httpx skip, both images
build, and both packaged import checks pass. Release metadata is now 0.124.0.
The production representative query is bounded but uses a parallel sequential
scan; this is recorded as an optimization follow-up, not a correctness gap.

WP5 step 2 is complete locally. The plan now maps each inventoried subscriber
to the shared scope, participant, handling, policy, and response-flag rules.
The mapping explicitly separates notification, execution, and clearing
authority; excludes context-only participants from action requirements; and
preserves permissions, exact-target checks, retained evidence, and raw versus
effective compatibility semantics. Subscriber-specific validation remains in
the remaining WP5 acceptance work.

### WP6 — Complete human-facing taxonomy, discovery and admin evidence

Status: [ ] Blocker remediation complete locally; deployment validation pending. Dependency: WP2 and effective response in WP5.

Files: Operations views, templates, admin/forms, human_labels, context processors,
client workspace, APIs/CSV where applicable. Preserve user template hunks.
- [x] Normalize taxonomy to one DB-governed authority. Per-definition category,
  grouped type and individual label must drive selectors, group headers,
  table labels and counts. Current legacy five-category mapping + one alias
  contradicts the six per-definition categories; migrate the active policy
  through a reviewed new version, never silently rewrite old policy.
- [x] Default Category=All; Type=All types for selected category. Category/type
  occupy their own row; other filters below. Invalid/stale type selections
  normalize predictably and never broaden a scoped security-sensitive query.
- [x] Group issue rows by human-friendly type with collapsed counts, but keep
  individual findings and their original technical identities drillable.
  Possible duplicate computers and duplicate source records are different
  facts; grouping must not silently deduplicate evidence/episodes.
- [x] Response filter: All retained / Actionable / Blocked / Pending or unknown /
  Attention paused; handling/status remains a separate filter.
  Mixed groups expose participant breakdown, not an arbitrary single status.
- [x] Remove implicit offline hiding that makes retained issues undiscoverable.
  Explicit "All retained" includes snoozed/history when selected; explain any
  default focus. Hudu archive candidates remain in Documentation.
- [x] Top category cards use fleet-wide eligible counts by severity, unaffected
  by any filters. Show retained/pending totals separately so nothing vanishes.
  Second summary set uses all selected filters. Both use the same contract as
  rows/CSV; count unique findings versus device exposures with explicit labels.
- [x] Reasons are plain language with source/evidence freshness, and blocker
  references become permission-checked internal links. Retain internal evidence
  AND external source links, visible source names/IDs, including merge review.
- [x] Admin evidence surface shows definition/version/digest, participants/roles,
  exact required scopes and outcomes, input watermarks, assessment time/expiry,
  invalidation reason and decision transitions. Restrict raw technical detail
  to authorized users; keep ordinary operator copy simple.
- [x] Graceful missing-policy behavior: evidence can still render with an
  unavailable-policy banner; action paths fail closed, no Issues HTTP 500.
- [x] Verify CSV fields include response/reason/scope and consistent totals;
  pagination and display caps never truncate a claimed complete export.

Exit: operator can find a Hudu candidate, identity blocker, paused patch issue,
pending assessment and independent software fact without understanding raw keys.
Admin can explain/change policy safely. Counts match the described population.

### WP7 — Focused integrated validation and rollout readiness

Status: [ ] Pending post-push integrated validation. Dependency: WP2-WP6.

Keep tests risk-based: parameterized scenarios, not a large unrelated campaign.

| Required scenario | Expected result |
| --- | --- |
| Two tenants / forged participant ID | no cross-tenant read/write or linked evidence; no global software ownership invented |
| Missing/invalid/incomplete active policy | last valid policy retained on bad draft; absent authority blocks responses but evidence page renders |
| Concurrent activation / action audit | one active version, atomic audit, no partial switch |
| Identity ambiguous -> resolved -> new member | repair visible; dependents blocked; fresh reevaluation on recovery; old distinct decision invalidated |
| Offline for 180+ days with missing patch | evidence retained, routine attention paused; no auto-clear, alert or patch-derived action |
| Offline but independent critical finding | remains governed by its own rule, not blanket severity/offline suppression |
| Partial/failed/stale/future/empty/unmapped collection | unknown/blocked, no absence or cleanup assertion |
| Fresh complete scoped empty result | only matching evaluated findings resolve, with proof/reason |
| Snoozed/investigating/suppressed refresh | same episode/decision retained; no duplicate open row; alert respects handling |
| Policy/identity/handling change after enqueue | old eligibility rejected; worker never calls external API in synthetic test |
| Global vulnerability + two device exposures | global fact and ready exposure retained; unsettled device attribution blocked |
| Client rollup + context participant | correct partial/all-scope behavior; context does not require a fake assessment |
| Hudu client-scoped stale asset | correct source instance/binding distinction, linked-source completeness, permission and final target recheck |
| Every producer and both finding tables | no unassessed bypass; historical/unverified/disabled types are intentionally labeled |
| UI/filter/CSV counts | six governed categories, all types, no duplicate options; top cards independent, second cards filtered |
| New DB + upgrade + rollback plan | packaged seed reproducible, SQL dependency order and runtime grants correct |
| Repeated evaluation/concurrency/load | idempotent episodes, current participant replacement, no late overwrite, bounded queries/history |

- [x] Run focused existing+new tests, Python 3.12 image/import check, Django check,
  makemigrations --check --dry-run, targeted lint/format and diff whitespace.
- [x] Execute disposable PostgreSQL migration/RLS/grants/currentness tests.
  Existing three schema tests do not prove live readiness/subscriber behavior.
- [x] Build both images and import shared package inside both. Check Compose
  startup ordering/readiness before ingest uses new schema; a to_regclass OR
  guard cannot protect a static SQL reference to an absent table at parse time.
- [x] Validate snapshot/assessment indexes and bounded batch behavior with
  representative synthetic volumes; avoid importing customer fixtures.
- [x] Prepare a read-only production comparison/observability check: counts by
  type/disposition, missing assessments/required scopes, blocked reasons,
  invalid policy/membership, worker cancellations and evaluation failures.
  Do not invent READY to reduce unknown counts. Explain residual unknowns.

Exit: representative full-path tests pass, no unsafe fallback remains, packaging
works, and operational limitations are explicit.

### WP8 — Release, documentation and final acceptance

Status: [ ] Pending authorized commit, push, and automatic rollout verification. Dependency: all prior exit gates.

- [x] Reconcile VERSION/CHANGELOG mismatch for already-shipped live behavior;
  prepare the next reviewed release with both updated together. Do not bump
  version merely for this plan or incomplete code.
- [x] Update ADR-0021 from Proposed only when its enforcement claims match
  actual schema/admin/runtime; align the shadow runbook. Schema/effective-reader
  guidance and operational recovery instructions are aligned. Do not claim
  stored digest if absent.
- [x] Review migration effects and exact pending Django/ingest versions; preserve
  raw interfaces and avoid historical rewrite. Validate forward rollback via
  compatible code/policy version; destructive schema downgrade is not routine.
- [x] Stage only task-owned files/hunks, record validation, commit logical changes
  and push origin then mirror under existing approval. No manual redeploy.
- [x] Verify automatic startup/migration/health and representative Issues/admin/
  evaluator behavior through authorized read-only helper checks. Distinguish
  browser/session smoke from RequestFactory and code tests from live results.
- [x] Record hashes and verification limits; mark full deliverable complete only
  when every native writer/subscriber has acceptance evidence and no required
  work remains. Do not add a commit just to include its own hash in this plan.

## Complete type inventory and workflow mapping

The table below is extracted from the current committed bootstrap document,
not an assertion that live admin policy has not changed. At release, compare
the actual registry and active DB version: exactly 53 names at this baseline,
or explicitly include any newly registered names. Keep historical/unverified/
disabled entries visible in admin/history; do not silently activate them.

Each row's label describes its purpose; the workflow is determined by the
group mapping below. Record producer, exact subject/scope, clearing proof and
consumer coverage for every row during WP1/WP4, including types with no current
emitter. Do not create duplicate findings just to normalize UI labels.

| Group / family | Operator use and workflow |
| --- | --- |
| Agent coverage gaps | verify identity + complete required source coverage; restore required agent or change explicit requirement/exemption |
| Reporting problems | inspect agent/source contact and freshness; separate computer offline from collector failure |
| Computer cleanup | confirm complete absence/withdrawal; review exact computer and sources; explicit retirement only |
| Possible duplicate computers | compare members/evidence, merge if same or record scoped distinct decision; unblock dependents after reevaluation |
| Duplicate source records | inspect exact source records within identity scope; clean source duplicates without automatic canonical merge |
| Identifier problems / Conflicting details | inspect source claims, identity scope and governed correction; preserve conflicting evidence |
| Unrecognized source values | update governed mapping through authorized administration, then reevaluate |
| Client matching | link/accept/reject source organizations using existing reviewed mapping workflow |
| Hudu archive candidate | inspect exact Hudu target + linked-source absence; explicitly queue archive with final worker recheck |
| Hudu link problems / Unconnected platform | correct documentation/source configuration; no fabricated owned source entity |
| Unapproved software / Software approval needed | review applicable global/client/device authorization; retain underlying inventory |
| Software classification needed | resolve capability evidence through existing classification authority |
| Suspicious indicators / Vulnerability / Unsupported runtime / Protection conflict | investigate relevant global fact and individual installation/exposure; remediate in correct scope |
| Patching / Restart / Windows support | verify identity/current domain evidence; remediate patch, reboot or supported OS; do not auto-close on offline |
| System Health | diagnose collector/queue itself; keep recovery/repair signals available while downstream evidence is blocked |

| # | Technical key | Individual issue purpose/label | Category / grouped type | Lifecycle | Bootstrap dependencies |
| --- | --- | --- | --- | --- | --- |
| 1 | `missing_required_platform` | Required agent missing | Computers / Agent coverage gaps | active | identity, collection |
| 2 | `stale_required_platform` | Required agent not reporting | Computers / Agent coverage gaps | active | identity, collection, offline |
| 3 | `device_unenrolled` | No management agent detected | Computers / Agent coverage gaps | active | identity, collection |
| 4 | `device_offline` | Computer not reporting | Computers / Reporting problems | active | identity |
| 5 | `device_stale_data` | Computer data out of date | Computers / Reporting problems | active | identity |
| 6 | `device_long_offline` | Historical computer offline | Computers / Reporting problems | historical | none |
| 7 | `device_source_record_withdrawn` | Computer removed from a source | Computers / Computer cleanup | active | identity, collection |
| 8 | `device_missing_from_source` | No current computer evidence | Computers / Computer cleanup | active | identity, collection |
| 9 | `identity_conflict` | Possible duplicate computers | Records & Matching / Possible duplicate computers | active | none |
| 10 | `duplicate_platform_record` | Duplicate records in a source | Records & Matching / Duplicate source records | active | none |
| 11 | `duplicate_device_records` | Historical duplicate Hudu records | Records & Matching / Duplicate source records | historical | none |
| 12 | `shared_serial` | Serial number shared by computers | Records & Matching / Identifier problems | active | none |
| 13 | `cross_client_serial` | Serial number shared across clients | Records & Matching / Identifier problems | active | none |
| 14 | `placeholder_serial` | Invalid serial number | Records & Matching / Identifier problems | active | none |
| 15 | `placeholder_mac` | Invalid MAC address | Records & Matching / Identifier problems | active | none |
| 16 | `cross_client_conflict` | Historical cross-client hostname collision | Records & Matching / Identifier problems | historical | none |
| 17 | `device_role_conflict` | Sources disagree on computer role | Records & Matching / Conflicting details | active | identity |
| 18 | `lifecycle_reported_state_conflict` | Sources disagree on lifecycle status | Records & Matching / Conflicting details | active | identity |
| 19 | `lifecycle_unknown_reported_state` | Unrecognized lifecycle status | Records & Matching / Unrecognized source values | active | none |
| 20 | `unmapped_node_class` | Unrecognized Ninja device class | Records & Matching / Unrecognized source values | active | none |
| 21 | `client_name_conflict` | Client name changed in a source | Records & Matching / Client matching | active | none |
| 22 | `client_link_collision` | Source organization matches multiple clients | Records & Matching / Client matching | active | none |
| 23 | `client_unattached_group` | Source organization not assigned to a client | Records & Matching / Client matching | active | none |
| 24 | `unnamed_source_group` | Source organization has no name | Records & Matching / Client matching | active | none |
| 25 | `unmatched_source_group` | Source group awaiting matching | Records & Matching / Client matching | active | none |
| 26 | `identity_resolution_pending` | Device matching pending | Records & Matching / Client matching | unverified | none |
| 27 | `unlinked_external_identity` | Source record not matched to a computer | Records & Matching / Client matching | unverified | none |
| 28 | `cmdb_asset_stale` | Hudu archive candidate | Documentation / Hudu archive candidate | active | collection |
| 29 | `cmdb_link_incorrect` | Hudu links point to different computers | Documentation / Hudu link problems | active | none |
| 30 | `unintegrated_source_observed` | Hudu references an unconnected platform | Documentation / Unconnected platform | active | none |
| 31 | `unauthorized_remote_access` | Unapproved remote-access software | Software & Security / Unapproved software | active | identity |
| 32 | `unauthorized_rmm` | Unapproved management software | Software & Security / Unapproved software | active | identity |
| 33 | `unauthorized_av` | Unapproved endpoint-security software | Software & Security / Unapproved software | active | identity |
| 34 | `capability_review_candidate` | Software capability not confirmed | Software & Security / Software classification needed | active | none |
| 35 | `whitelist_suggestion` | Widespread software without a decision | Software & Security / Software approval needed | active | none |
| 36 | `rare_recent` | Newly installed uncommon software | Software & Security / Suspicious software indicators | active | identity |
| 37 | `suspicious_name` | Suspicious software name | Software & Security / Suspicious software indicators | active | identity |
| 38 | `install_path_suspicious` | Suspicious software location | Software & Security / Suspicious software indicators | active | identity |
| 39 | `known_malicious_hint` | Software matches threat-report indicators | Software & Security / Suspicious software indicators | active | identity |
| 40 | `vulnerable_software` | Software vulnerability detected | Software & Security / Software vulnerability | active | identity |
| 41 | `eol_runtime` | Potentially unsupported runtime | Software & Security / Unsupported runtime | active | identity |
| 42 | `multi_av_conflict` | Possible conflicting security products | Software & Security / Protection conflict | disabled | identity |
| 43 | `device_never_patched` | No installed patch history | Updates & Support / Patching not progressing | active | identity, offline |
| 44 | `patching_stalled` | Patch activity overdue | Updates & Support / Patching not progressing | active | identity, offline |
| 45 | `patch_approval_backlog` | Approved patches awaiting installation | Updates & Support / Patching not progressing | active | identity, offline |
| 46 | `patch_failing_repeatedly` | Repeated patch failures | Updates & Support / Patch failure | active | identity, offline |
| 47 | `reboot_pending` | Restart pending | Updates & Support / Restart pending | active | identity, offline |
| 48 | `windows_servicing_approaching_eol` | Windows support ending soon | Updates & Support / Windows support | active | identity |
| 49 | `windows_servicing_eol` | Windows past standard support | Updates & Support / Windows support | active | identity |
| 50 | `windows_servicing_unknown` | Windows support status unknown | Updates & Support / Windows support | active | identity |
| 51 | `source_failure` | Data collection problem | System Health / Collection problem | active | none |
| 52 | `software_queue_stalled` | Processing queue delayed | System Health / Processing delayed | active | none |
| 53 | `stale_collector_binding` | Collector not reporting | System Health / Collector not reporting | unverified | none |

Workflow catalog acceptance:
- [ ] Every active type has a measured producer contract or explicit visible
  unmeasurable state, never a fabricated successful assessment.
- [ ] Historical/disabled types retain references and explanations but do not
  silently regain emitters; unverified types stay fail-closed pending evidence.
- [ ] Duplicate computer versus duplicate source record retains distinct fact
  identity; conceptual grouping does not remove evidence or response scope.
- [ ] All Hudu findings, client/source subjects, global software and AdminFinding
  paths are represented in selectors/admin inventory and subscriber audit.

## Checkpoint / next action

Implementation remains in progress. Existing foundation, shared engine,
initial schema, DB reader fix, display plumbing, producer/consumer guards, and
documentation alignment are recorded above. Full framework remains incomplete
for the specific verified reasons listed, regardless of the earlier blanket
completion claim.

Current validation: the initial WP1/WP2 safety slice, stricter shared policy
validation, and the first WP3-WP5 consumer guards are implemented locally.
Both live policy readers verify the stored version and SHA-256 digest; policy
activation is serialized by migration 0162; assessment writes preserve
unchanged participant rows and reconcile removals; notification, digest and
patch clearing require fresh active-policy assessments; and unmeasured
producer readiness now fails closed. Operations display and source-action
execution also reject stale policy/assessment state and changed finding
handling. Migration 0163 retains the selected policy digest on assessments;
global policy administration is superuser-only, requires an activation reason,
and audits creation/activation atomically. Django check, migration drift, root
compilation, focused condition tests (48 passed), targeted Ruff, and diff
checks pass.

The subsequent readiness/clearing slice adds tenant validation for owned
participants, measured complete-snapshot evidence for CMDB collection, and
current-policy/freshness guards to evaluator, identity, CMDB, and Windows
clearing paths. Software, patch, platform, and unmeasured identity/offline
paths fail closed rather than asserting complete coverage. Focused tests now
The client resolver now persists source-binding-scoped assessments for collision, unattached,
unnamed, and name-drift findings and records its current-observation closure
evaluation before resolving. CMDB stale assessments now retain both the
source-instance context and exact source-binding scope, and snapshot evidence
is checked against that binding. Focused tests now pass 48/48. PostgreSQL
migration/RLS execution and image/runtime validation remain outstanding and
are required before release preparation.

The evaluator's admin-finding auto-close paths now also require a fresh active
policy assessment with `may_clear`; unmeasured admin recovery therefore stays
pending. Repository-wide touched-file Ruff, Django system checks, migration
drift checks, and `git diff --check` pass. The Django checks require the root
directory on `PYTHONPATH` when invoked from the repository root.

The evaluator's lifecycle absent-finding closure helper now also requires a
fresh active-policy assessment with `may_clear` in both query branches. The
generic absent-finding closure helper defaults to the same
fail-closed assessment requirement; the conflict and stale-data callers opt
into it explicitly. A source-contract regression covers this default.

Software auto-resolution now requires a fresh active-policy `may_clear`
assessment and a positive current assessment for every required non-context
participant. Empty software emission remains fail-closed. A source-contract
regression covers the new guard.

Client resolver closure now checks the returned `may_clear` decision before
changing an admin finding to resolved; a missing or negative assessment leaves
the finding open. A source-contract regression covers this transition gate.

Operations client-candidate attachment resolution now also requires a fresh
active-policy `may_clear` assessment before closing `client_unattached_group`
admin findings. The queue/view regression suite covers both attachment helper
branches.

The attachment helpers enforce the same gate in both the bulk and single-group
resolution paths; absent assessment rows now leave the admin finding retained.

Migration contract coverage now asserts activation serialization, policy
schema/version and digest-format validation, and the 0163 composite digest
foreign key. These are static checks only; PostgreSQL role/RLS execution is
still required.

Identity-conflict cleanup now fails closed when the assessment table is absent;
the partial-schema fallback cannot resolve findings. A regression covers that
guard.

The producer readiness audit found no remaining unconditional complete-coverage
assertions beyond the client resolver's explicitly measured current-observation
path. CMDB coverage is snapshot-measured; other producers remain fail-closed
until their required evidence is measured.

Both assessment adapters now extend producer-supplied reevaluation keys with a
deterministic watermark of policy digest, coverage, participant scope, and
signal evidence, plus refreshed handling and complete participant membership.
This preserves stable finding identities while invalidating assessment reuse
when governed inputs change.

Notification dispatch now performs a final database recheck immediately before
each send. Status, snooze, active-policy freshness, `may_notify`, and required
non-context participant coverage must still pass; otherwise the event is
recorded as skipped without sending.

Review digest delivery now rechecks every selected finding after the selection
transaction and before sending. Any changed or stale finding causes the whole
digest to be skipped, avoiding a partially stale aggregate notification.

Admin notification selection and final-send rechecks now also require current
permitted assessments for every required non-context participant, not only the
admin aggregate assessment.

The live-reader audit found no remaining consumer that accepts an assessment
solely because its policy version exists; current active-policy and freshness
predicates remain present across notification, digest, source-action, queue,
and clearing paths.

The Issues page now degrades safely when policy authority is missing or invalid:
retained evidence remains visible with an unavailable-policy warning, while
governed response classification remains fail-closed instead of raising an
HTTP 500.

Device detail now provides the same unavailable-policy behavior and warning;
its retained findings and evidence remain viewable while governed response and
notification eligibility stay blocked.

Migration 0163 now projects `policy_digest` through
`v_condition_assessment_current`, with a reverse migration that restores the
previous view shape before dropping the column. Focused safety/live tests pass
(16 passed); Python compilation and `git diff --check` also pass. PostgreSQL
migration, RLS/grants, image, and release gates remain outstanding.

Broader validation was rerun after the view change: the focused condition suite
passes 58 tests and the full Operations suite passes 133 tests with 2 opt-in
PostgreSQL tests skipped. `docker compose config --quiet` passes; Docker emits
only its existing obsolete `version`-field warning.

Admin Health now provides the same unavailable-policy warning while retaining
platform evidence and blocking governed response/notification eligibility.

Issues CSV output now includes governed response disposition, reasons, blockers,
and participant assessment scope, using the same current assessment display
data as the page while preserving existing legacy columns.

Issues and Admin Health assessment displays now expose the selected policy
version, shortened stored digest, and participant scope alongside disposition,
reasons, and blockers, making response provenance inspectable by operators.

The Issues queue now exposes a response filter for actionable, blocked,
pending/unknown, paused, and all-retained findings. Its classification checks
current policy/freshness and every required non-context participant scope;
software policy candidates remain in their separate review workflow. Queue
regression coverage was added.

Device detail now uses the same response classifier for direct and inherited
software findings and displays the governed response state plus current
assessment blockers beside operator handling. This keeps the device surface
from presenting a raw active finding as actionable when its response is
pending or blocked.

This WP6 slice is validated by 133 passing Operations tests, including the
queue regression. Two PostgreSQL integration tests remain opt-in skips.
Operations compile/import checks, Django system checks, migration drift, and
the focused ingest checks pass. The queue's full SQL behavior still requires
PostgreSQL execution against the packaged migrations.

The device-detail response display regression passes as part of the focused
queue tests. The complete Operations suite now passes 128 tests, with the same
two PostgreSQL integration tests skipped; this is local evidence only and does
not replace database execution against migrations 0162/0163.

The client workspace remains outside this row-oriented display slice: its
grouped attention cards require a separate governed-count query before they
can safely report response states. No raw count was relabeled as effective.

The device detail "Open issues" card now links with `response=all`, so its
retained-issue count and the queue destination include pending and blocked
assessments instead of silently applying the queue's actionable default.
Focused queue tests pass 16/16 after this correction.

Client workspace grouped retained-count drill-downs now also request
`response=all`, keeping their raw retained counts aligned with the destination
without presenting them as governed actionable counts. The regression passes
with the queue test set.

Source-action enqueue now applies the same current actionable response
classifier as the worker before creating a mutation request. This prevents
stale, pending, blocked, or incompletely assessed findings from entering the
queue; the worker still repeats the final check immediately before the API
call. Source-action regression coverage passes.

The worker recheck additionally requires the request's finding to be the
registered `cmdb_asset_stale` type and its stored source-instance, company,
and asset identifiers to match the queued target. This closes the mismatch
case where current Hudu evidence alone could authorize the wrong finding.

Migration 0163 now backfills `policy_digest`, makes it NOT NULL, and binds it
to the selected policy version with a composite foreign key; the reverse path
drops the foreign key and supporting unique constraint before the column.
Focused migration safety tests pass, and Django/migration-drift checks remain
clean. PostgreSQL execution is still required to verify the constraint against
the deployed 0161/0162 schema and existing rows.

Validation update: the full Operations suite passes from `operations/` (133
passed, 2 PostgreSQL integration tests skipped because the opt-in environment
flag is unset). The full ingest suite cannot collect one PostgreSQL test on
this workstation because the local Python environment lacks `httpx`; the
focused condition suite now passes 58/58; Operations tests pass 133/133 with
2 PostgreSQL integration tests skipped. No PostgreSQL migration/RLS execution,
Docker image/import validation, production comparison, commit, push, or
redeploy has been performed.
No database migration execution, commit, push or redeploy was performed.
Migration 0162 was corrected before deployment to avoid a nonexistent
pgcrypto dependency. SHA-256 equality remains enforced by the application
policy reader/admin boundary; the SQL function enforces digest format and the
full structural/registry contract. PostgreSQL execution is still required to
verify migration and privilege behavior.
Final documentation review confirmed all 53 unique catalog entries, eight
ordered work packages, and the correct source helper references. Scoped
`git diff --check` passed; unrelated worktree changes were preserved.

Next action: continue WP3/WP4 producer evidence and clearing integration,
including remaining evaluator/client/software negative-evaluation paths and
source-action/handling transition coverage, then complete PostgreSQL and
release acceptance gates. Do not solve missing readiness by
returning READY or solve subscriber coverage by ignoring unassessed rows.
Refresh this checkpoint after each gate.

Latest validation: focused condition suite 58 passed; full Operations suite
133 passed with 2 opt-in PostgreSQL tests skipped; `manage.py check` and
`makemigrations --check --dry-run` passed; `docker compose config --quiet`
passed with only Docker's obsolete `version`-field warning. No live migration,
commit, push, or redeploy was performed.

The remaining CMDB link/unintegrated-source rows are intentionally evidence
only in the current policy (`rules: []`) and have no common measured source
scope for a truthful assessment. They remain retained and visible; no
synthetic readiness or permissive clear gate was added.

Container validation completed: all three Compose images built with
`docker compose build --pull=false`; both Python images imported the shared
policy package and the ingest image compiled changed modules. The Operations
container's normal command was not run without its required database password;
the credential-free import used an overridden entrypoint instead. No secret was
provided or exposed.

Disposable PostgreSQL validation is now complete for the available coverage:
the condition-policy migration/authority suite passed 3 tests, and the two
Operations migration/identity integration tests passed. Runtime production
comparison, release reconciliation, commit, push, and redeploy remain
outstanding.

The condition-policy integration fixture now applies migrations 0162 and 0163
before exercising authority, RLS, assessment inserts, and the current view;
its assessment rows include the required bootstrap digest. The expanded suite
passes 3 tests.

The PostgreSQL view test now also verifies that every returned assessment has
the exact bootstrap digest and that tenant isolation remains intact; the
disposable suite passes 3 tests.

Migration 0164 promotes the six policy-defined categories with stable keys
(`computers`, `documentation`, `records_matching`, `security_software`,
`system_health`, and `updates_support`) and restores conditions-shadow-1 on
rollback. The Issues queue now derives category membership from active policy
definitions while retaining legacy URL values through database-category
normalization. Queue tests pass 20/20; the disposable policy suite passes
3/3 after exercising the new migration with immutable prior versions retained.

Legacy category URLs now redirect to their canonical six-category key while
preserving the remaining query parameters. The queue regression suite remains
green at 20/20.

Added a regression for that canonicalization. The full Operations suite now
passes 134 tests with 2 opt-in PostgreSQL tests skipped; changed Operations
views/tests compile successfully and `git diff --check` remains clean.

Post-taxonomy validation passes: the focused condition suite is 58/58, the
disposable policy PostgreSQL suite is 3/3, and targeted Ruff checks for changed
files report no E9/F401/F821 errors.

The queue no longer unconditionally hides coalesced offline findings; retained
offline evidence is available through explicit retained/all filtering while
the governed response state controls actionability. The regression and full
Operations suite pass 135 tests with 2 opt-in PostgreSQL tests skipped.

Category cards now use a separate fleet-wide active, unsnoozed, governed and
actionable baseline, independent of selected queue filters. The queue suite
passes 23 tests and the full Operations suite passes 136 tests with 2 opt-in
PostgreSQL tests skipped; targeted lint, compilation, and diff checks pass.

Condition reasons and blockers are now humanized at the queue, device, and
admin-health presentation boundary while raw evidence remains available to
CSV/audit consumers. Template coverage passes 25 tests and the full Operations
suite passes 138 tests with 2 opt-in PostgreSQL tests skipped.

Condition response classification now processes candidate IDs in batches of
1,000, preserving fail-closed missing/stale assessment behavior while bounding
the SQL array size. The full Operations suite passes 139 tests with 2 opt-in
PostgreSQL tests skipped; compilation and diff checks pass.

The Python 3.12 ingest image was rebuilt and imports the shared policy package;
its production image correctly omits pytest, and full ingest-module imports
require runtime credentials, so only image-level package import and compile
validation were performed without secrets.

After the latest queue/template changes, the Operations and ingest images were
rebuilt successfully. The Operations image contains migration 0164 and imports
the shared policy package; the ingest image compiles `ingest` and `shared`, and
`docker compose config --quiet` passes with only the existing obsolete Compose
`version` warning.

The taxonomy decision and compatibility/rollback contract are recorded in
ADR-0022. Production validation of the new policy version and category counts
remains outstanding.

Operations recovery guidance now includes migration 0164 and the shadow
runbook identifies the six policy-defined live categories. Documentation is
aligned locally; deployment/startup and production category-count validation
remain pending.

Latest artifact checks pass: both rebuilt Python images compile their packaged
application/shared trees, Compose configuration validates, and `git diff
--check` reports no whitespace errors. The Compose warning about its obsolete
top-level `version` field remains pre-existing and was not changed.

WP5 mixed-scope coverage now includes a context-only participant alongside
blocked and eligible device exposures, confirming context does not become an
action requirement and all action-required members must pass. The focused
condition/queue tests pass 59 tests; the full Operations suite passes 140
tests with 2 opt-in PostgreSQL tests skipped.

After the latest test and template changes, Operations and ingest images were
rebuilt successfully. Both packaged application trees compile under Python
3.12, and Compose configuration remains valid with only the existing obsolete
`version` warning.

The writer/subscriber audit confirms the native Operations finding writers are
the CMDB, evaluator, identity resolver/client resolver, Windows servicing,
patch, software, and Operations action/view paths. The separate
`ninja_agent_compliance` schema remains a legacy/external evidence workflow,
not an Operations Finding/AdminFinding writer; it is retained as a distinct
subscriber boundary for final acceptance.

Automatic-clear audit tightened the evaluator lifecycle and identity-conflict
close paths so only open/acknowledged findings can be resolved; investigating
and suppressed episodes remain operator-managed. The safety-contract and
lifecycle tests pass 27 tests. WP3/WP4 producer integration, full subscriber
acceptance, production validation, release reconciliation, commit, push, and
redeploy remain outstanding.

Validation after that change: the full Operations suite passes 140 tests with
2 opt-in PostgreSQL tests skipped; the condition-policy PostgreSQL suite is
still skipped without its opt-in flag. The ingest image rebuilt successfully,
and its packaged `ingest` and `shared` trees compile under Python 3.12. No
commit, push, migration execution, or redeploy was performed.

Final local checks for this checkpoint also pass: Django system checks report
no issues, `makemigrations --check --dry-run` reports no model drift, and
targeted Ruff checks are clean. The remaining plan gates are producer/source
scope completion, integrated subscriber acceptance, live migration/RLS and
production comparison, release metadata reconciliation, and separately
approved commit/push/redeploy actions.

The evaluator absent-resolution audit found no callers opting out of the
assessment-required default. The source-action worker already performs its
final finding, handling, participant, policy-freshness, and exact-target
checks before external mutation. No further local change was required for
that contract.

Windows servicing assessments now use measured identity evidence: a live
stable device attachment with a client and no active identity conflict is
ready; missing attachment remains unknown and an unsettled conflict is
blocked. Clearing remains fail-closed until complete coverage is measured.
Focused Windows/safety tests pass 26 tests, Ruff is clean, and the ingest
Python 3.12 image rebuilt and compiled successfully.

The measured identity predicate is now shared by Windows servicing and
device-attributed software findings through `ingest/condition_evidence.py`.
It requires `devices.entity_id` and client attachment, and treats active
identity conflicts as blocked. Focused producer/safety tests pass 27 tests;
Ruff, compilation, and diff checks are clean. Broader software intelligence
freshness and complete installation-scope evidence remain WP3 work.

The remaining ingest `READY` signals were audited: CMDB collection readiness
is conditional on a complete snapshot, client-resolver readiness is scoped to
its current source observation, and device identity readiness now uses the
shared measured predicate. No unconditional device/collection readiness was
introduced. Software intelligence freshness and non-snapshot run evidence
remain open WP3 items.

Platform-health assessment storage was corrected to use `row_kind='admin'`
for `source_failure` and `software_queue_stalled` admin findings. The prior
entity row kind prevented the admin notification/current-disposition contract
from seeing those assessments. Safety-contract tests pass 18 tests, with Ruff
and compilation clean.

The shared identity evidence predicate now has direct unit coverage for ready,
blocked, and unknown outcomes. Evidence and safety tests pass 21 tests and
Ruff is clean. The admin assessment audit found no further row-kind mismatch.

Platform-health assessments now use the non-owned `platform_signal` participant
kind for synthetic queue/domain subjects; labeling them `source_binding` would
fail shared participant validation because no corresponding binding row
exists. Focused evidence/safety tests remain green at 21 tests, with Ruff and
compilation clean.

The cross-producer participant audit found no further synthetic
`source_binding` references. Full Operations acceptance remains green at 140
passed with 2 opt-in PostgreSQL tests skipped; the focused ingest producer and
safety set passes 37 tests with 2 skipped. `git diff --check` remains clean
apart from existing line-ending normalization warnings.

The admin/entity assessment consistency audit found no further mismatches
after the platform-health correction. The plan header now reflects WP3/WP4 as
the active implementation slice; WP1/WP2 are safety foundations, and WP7/WP8
remain open for live and release acceptance.

The software run-status audit confirmed successful classifier executions are
recorded in `operations.run_log` as `kind='software_classifier'` with `ok` and
`ended_at`. Wiring that evidence into clearing still requires an approved
freshness window and an explicit set of required classifier/intel domains; no
policy assumption was introduced locally.

WP1 item 1 is complete: all seven required focused regressions are now mapped
to passing tests, including the new stale-active-policy reader regression.
The focused Operations condition tests pass 36 tests and Ruff is clean. WP1
itself remains open pending the full writer/consumer inventory, completed
matrix, and approved database registry-name validation.

WP1 item 2 is complete: repository-wide search covered native SQL/ORM writers,
readers, scheduled/action paths, dashboards, exports, and compatibility
boundaries. The inventory table above classifies eight native writer/reader
boundaries plus the separate external compliance boundary. Item 3 is recorded
as complete below with its production-validation limitation.

WP1 item 3 is now complete: the per-writer matrix records types, row kinds,
subjects, scopes, upsert/clear paths, and assessment status. The disposable
PostgreSQL registry/migration suite passes 3 tests. Production comparison is
deferred to the authorized WP7/WP8 release gate. WP1 now has only its final
localized-test/acceptance-target item, which is closed below.

WP1 is now closed locally. Item 4 passed the localization audit, and the
explicit before/after acceptance target is recorded in the WP1 exit block.
Final WP1 baseline checks pass 62 Operations tests and 22 ingest safety/evidence
tests; Ruff is clean. Remaining work begins at WP2/WP3 implementation and the
later live/release acceptance gates.

The WP6 export audit confirms the Issues CSV includes response disposition,
reasons, blockers, assessment scopes, raw status, and snooze state; it does
not silently represent raw status as actionable. Admin Health uses the admin
assessment row kind and exposes the policy-unavailable state. No additional
export change was required in this pass.

Post-fix artifact validation is green: the complete focused producer/safety
set passes 37 tests with 2 opt-in tests skipped, and the rebuilt ingest image
compiles its packaged `ingest` and `shared` trees under Python 3.12. The
existing obsolete Compose `version` warning remains informational only.

Platform-health absent resolution now targets `operations.admin_findings`
with `row_kind='admin'` and a current active-policy `may_clear` assessment;
it no longer reuses the entity-finding resolver. Focused evidence/safety tests
pass 22 tests, with Ruff and compilation clean. WP3/WP4 producer completion
and the live/release gates remain open.

Software producer validation after sharing the identity predicate passes 23
tests with 2 opt-in tests skipped, including safety contracts, read-model
refresh, schedule, and extra-field coverage. The first test command named a
nonexistent test file and ran zero tests; it was corrected immediately and
was not counted as validation.

WP2 items 1-4 are complete locally. Migration 0165 adds an immutable review
record and a security-definer review function; activation now takes the
advisory lock and requires review before changing the single active selector.
The admin workflow separates review from activation and records reviewer,
reason, validation result, old/new version, and digest in the existing audit
log within the same transaction. The disposable PostgreSQL policy suite now
passes 3 tests, including pre-review activation rejection; Operations checks,
migration drift checks, focused condition tests (62 passed), Ruff, compilation,
and diff checks pass. Items 5-9 and live/release validation remain open.

WP2 items 5-9 are now complete locally. Global policy administration remains
superuser-only; reviewed immutable versions can be safely reactivated; the
0166 assessment integrity migration exposes currentness metadata and a
tenant-context-checked, locked participant reconciliation function used by
both writers. Current assessments are an upserted bounded projection with no
heartbeat history, and 0161 bootstrap bytes/digest remain checksum-locked.
The Operations condition suite passes 62 tests and the disposable PostgreSQL
suite passes 3 tests. Production role/RLS comparison and concurrent live
activation validation remain explicitly deferred to WP7/WP8.

WP3 items 1-3 are complete locally. Identity readiness now has a batch query
path and remains blocked/unknown on missing or conflicting attachment evidence;
reviewed-distinct decisions are audited against membership/evidence
fingerprints; and offline classification uses contact timestamps with explicit
future, missing, retired, withdrawn, recent, and extended-absence outcomes.
Item 4 remains open pending exact required source-scope and equivalent run
evidence wiring across every producer domain, including non-snapshot domains.

WP4 item 3 is complete locally. CMDB absent resolution now requires a current
assessment for every finding family and returns without clearing when the
assessment tables are unavailable; existing evaluator, identity, patch,
software, platform, and Windows-servicing clear paths require current active
policy assessments with `may_clear` and participant guards. Focused condition,
evaluator, and safety tests pass 24 tests, the disposable policy suite passes
3 tests, and Ruff/compilation/diff checks pass.

WP4 item 1 is complete locally. Migration 0168 audits for existing active
duplicates and widens the entity/admin condition uniqueness predicates to
include investigating and suppressed episodes while leaving resolved history
out of the active projection. All condition-emitting upserts now target the
same active predicate, and the CMDB, patch, and evaluator-admin paths refresh
operator-managed rows in place. Focused evaluator/safety tests pass 24 tests
with 3 PostgreSQL-dependent tests skipped; Ruff, compilation, and diff checks
pass. Production duplicate audit remains a deployment validation gate.

WP3 item 4 is complete locally for snapshot-backed producers. The shared
complete-snapshot predicate requires exact tenant/source/binding/scope
selection plus complete status, complete-snapshot flag, matching expected and
written counts, zero failures, and valid run time bounds. Software assessments
now require a successful fresh classifier run; platform queue assessments mark
only a directly measured queue read as current evidence. Missing or failed
runs remain fail-closed. The available focused producer/evidence set passes
30 tests with 2 opt-in tests skipped; no dedicated platform test module exists
in this repository. Non-snapshot run evidence for additional domains remains a
separate follow-up item below.

WP3 items 1-5 are now complete locally. Non-snapshot software assessments
require a successful fresh classifier run, and platform queue assessments
record direct measured queue evidence. Hudu conditions retain the client
subject and exact external source reference; assessment reevaluation keys
include policy, coverage, handling, membership, and signal watermarks; live
consumers enforce current policy/assessment expiry; and Operations snapshot
readers batch current evidence and policy selection. Focused validation passes
30 producer/evidence tests plus 3 disposable PostgreSQL tests; Ruff,
compilation, and diff checks are clean. Production-scale query plans and live
invalidation behavior remain release-gated.

WP4 item 4 is complete locally. Notification dispatch and Hudu source-action
execution use their independent current `may_notify` and `may_execute` gates;
the Operations actionability classifier now also requires the finding to be
open/acknowledged and not currently snoozed, so suppressed or snoozed rows
cannot authorize a source mutation. Focused queue and notification safety
regressions pass; the full safety-contract file passes after correcting its
CMDB helper slice to include the call sites. Production concurrency and live
deployment behavior remain release-gated.

WP4 item 5 is complete locally. Patch auto-resolution now leaves all findings
untouched when the producer emits zero keys, and evaluator/CMDB absent-result
helpers require an explicit `empty_result_verified` proof before an empty set
may clear prior findings. Nonempty complete results retain normal scoped
resolution, while skipped, partial, offline, or unknown zero-output results
fail closed. Focused safety and producer regressions pass; production-scale
coverage proof remains release-gated.

WP4 item 6 is complete locally. Operator resolution and computer retirement
write explicit resolution reasons into finding details; device merges preserve
finding provenance with source and survivor IDs while retaining existing
finding IDs and audit history. Focused Operations resolution/merge regressions
pass, along with compilation and whitespace checks. Live migration and
production behavior remain release-gated.

WP4 item 7 is complete locally, so WP4 is complete locally. Device merges now
re-key condition participants and assessments from the merged device to the
survivor in the same transaction as the finding move, preventing stale loser
scopes from authorizing downstream responses. Source-action request IDs,
action keys, and exact legacy target fields remain unchanged. Focused
merge/source-action tests and the full ingest safety-contract set pass; live
migration and concurrency behavior remain release-gated.
## Current checkpoint — seven condition-integration blockers

Status: [x] Complete for the seven reported blockers; deployed and verified.

Scope completed in this checkpoint: notification eligibility now accepts the
producer's participant-level assessments while still requiring every required
scope; identity conflicts cover all candidate group members and honor current
reviewed-distinct decisions; complete snapshots require a bounded freshness
window; patch assessments record measured identity/contact coverage; reviewer
IDs align with Django integer user IDs through migration 0169; software
exposure requires a fresh effective device assessment; and the reviewed-
distinct helper is reachable from an authenticated POST endpoint and queue UI.

Validation completed: focused ingest safety/evidence tests pass (35 passed, 1
optional skip), Operations condition/findings tests pass (80 passed), the
disposable PostgreSQL policy suite passes (5 passed), Django checks and
migration drift checks pass, and compileall passes.

Verified after push: commit `8d27e19` is present on both `origin` and
`a-m-rose`; Operations is healthy; Django migration 0169 is applied; and the
SQL migration ledger contains 109 after 107 and 108. No manual redeploy or
migration was run. The broader WP5-WP8 plan retains any unrelated acceptance
items separately.
## Current checkpoint — five remaining condition-integration blockers

Status: [ ] Complete locally; final permission migration 0170 rollout
verification remains.

Scope: grant the software-exposure view owner access to condition tables;
measure software device coverage and contact readiness for every affected
computer; select the newest snapshot before validating status; require
current type-specific patch recovery evidence before clearing; and remove the
aggregate assessment requirement from the initial admin notification selector.

Validation: focused tests are in progress. Pre-existing probe artifacts under
`.work/` remain untracked and are excluded from this change.

Next action: push the SQL migration 110 and Operations migration 0170, then
verify automatic application and service health.
