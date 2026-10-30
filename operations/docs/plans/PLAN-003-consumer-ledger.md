# PLAN-003 — Findings producer and consumer ledger

Status: technical audit for design review, 2026-10-27. Baseline HEAD 80557f6
plus existing dirty worktree. No runtime changes. Execution details are in
[technical design](PLAN-003-technical-design.md); current operator contract is
[current design](PLAN-003-current-design.md).

Repository scan: Python AST/function inspection and references to Finding,
AdminFinding, operations.findings/admin_findings, v_issue_findings, finding_state,
participants/assessments and row_kind. Excluded historical migration bodies
from the runtime-file count, then audited current database objects separately.
36 runtime Python reference files below; not all need edits. Added shared
identity/UI/packaging surfaces are listed separately rather than pretending
the textual scan finds every dynamic dependency.

## R0 refresh — baseline `1176034` (2026-10-29)

Rescanned runtime Python for findings/assessment/state references and diffed every
ledger file since `80557f6`. Add these to the cutover inventory:

| Item | Finding access | Treatment |
| --- | --- | --- |
| `ingest/requirement_state.py` (added `cc5d936`, missed by the original scan) | Reads `condition_assessments` and `admin_findings` | Route through the common store/namespace adapters; include in conservation tests |
| `ingest/evaluator.py` `_reconcile_requirement_findings` (`0af8aac`) | New requirement-finding closure path | Common persistence and protected state writer; closure semantics unchanged |
| Migration `0356` function `operations.device_requirement_state_disagreements(bigint)` | Reads `findings` and `finding_state` | Database-object inventory; rebind to the unified ledger in M3/M4 |
| Uncommitted PLAN-030 edits in `views.py`/`urls.py` | Client-candidate accept views | Land before R3 per the R0 decision |

Other new scan matches were wording only. View commits since `80557f6` changed no
findings queries. Migrations `0354`–`0361` other than `0356` touch no findings objects.

## Runtime reference ledger

| File | Current responsibility | Required treatment / proof |
| --- | --- | --- |
| ingest/cmdb_findings.py | CMDB upserts, exact-asset stale conditions and client link/integration hints | Keep per-asset target/history. Use common persistence; implement only reviewed semantic changes. Evidence/queued action consistency test. |
| ingest/condition_evidence.py | Preserves excluded/operator episodes, switches details/timestamps by old table | Remove physical-ledger branching; preserve condition identity and suppression/closure semantics. |
| ingest/condition_priority.py | Priority-related SQL used by notifications/source actions | Audit against retained independent-risk and relationship contracts; removing UI Readiness must not bypass execution gates. |
| ingest/conditions.py | Assessment/participant writes, current handling lookup | One finding lookup; persisted namespace/hash adapter; preserve policy digest/currentness and bulk trigger coverage. |
| ingest/evaluator.py | Coverage, lifecycle, no-agent, naming/configuration, admin emitters and closure SQL | Common persistence across all producers; recognized-OS boundary retained. No blanket data repair. Verify all direct SQL against new indexes/subject rules. |
| ingest/finding_attention.py | State drift comparison/repair | Keep repair authority in SQL, extend namespace/relationship checks. Drift audit must not be called during read-only validation. |
| ingest/identity/client_resolver.py | Entity/admin source-group, naming/topology findings and resolution | Typed source-group/set subjects, client scope and decisions preserved. Correct new persistence/closure names without changing identity rules incidentally. |
| ingest/identity/findings.py | Computer identity finding episodes/evidence | Preserve IDs/current algorithms in storage slice; accepted ADR-0043 conversion waits for PLAN-004 scope measurements. |
| ingest/identity/resolver.py | Finding updates during identity/Computer changes | Keep merge/split provenance and Computer ownership updates; aliases/history survive. No invented subject UUIDs. |
| ingest/intel/windows_servicing.py | Raw SQL support-state finding sync | Preserve alternative stages/version evidence and key identity; align actual active-index predicate. |
| ingest/notifications.py | Two-ledger candidates, send-time authority checks, fingerprint/cooldown/events | Single source; namespace-aware guards; preserve fingerprint/state and recheck before delivery. No delivery activation. |
| ingest/notifications_digest.py | Entity-only review digest, authority checks | Use common selection/guards where eligible without broadening configured recipients/type eligibility. No duplicated admin send path. |
| ingest/patch_findings.py | Patch upserts, per-update/client conditions and resolution SQL | Preserve natural scope and mutually exclusive never/stalled predicates. Relationship corrections are explicit, not broad patch merging. |
| ingest/platform_findings.py | Admin source/Jobs/held-inventory upserts, exact dependency-parent closure | Convert subject shapes and persistence; prospective related symptoms use Covers rather than pretending repaired. Preserve old closure reasons. |
| ingest/software_readiness.py | Condition-derived per-Computer software eligibility/exposure support | Keep per-Computer evidence authority; namespace/hash adapters as needed, not a queue Readiness dependency. |
| ingest/software_reconcile.py | Product/version/installation desired-state upserts, prompt split and closure | Storage first unchanged keys; later approval manifest merges prompt work preserving histories, scoped uncovered installation rules and safeguards. |
| ingest/source_actions.py | Leased external mutations, exact finding/asset recheck | Keep FK/target idempotency; namespace-aware participant checks and current guarded actions. No retargeting or retrying unsafe work from alias alone. |
| operations/apps/core/admin.py | Admin registrations/policy configuration | Compatibility review, not automatic wholesale rewrite. Preserve permissions and audited configuration; remove writable legacy ledger registration if exposed. |
| operations/apps/core/capability_review_actions.py | Product/capability target deduplication and global curator decisions | Same-type/permission gates; common subjects/closure without merging approval semantics. |
| operations/apps/core/client_workspace.py | Client issue rollups | Consume shared scope/count definitions, including affected clients on non-Computer work; no parallel count rules. |
| operations/apps/core/conditions/live.py | Operations-side assessment/participant writer | Same identity/namespace/handling adaptation as ingest; DB trigger and policy integrity tests. |
| operations/apps/core/conditions/reader.py | Two-ledger repeatable-read comparison snapshot | Single-ledger read with preserved row namespace and explicit subject context; bounded diagnostic snapshot, no actionability fabrication. |
| operations/apps/core/conditions/review.py | Identity-reviewed decisions bound to condition/membership fingerprints | Preserve hashes and membership across migrations; legacy aliases cannot invalidate or broaden reviewed evidence. |
| operations/apps/core/context_processors.py | Navigation issue count | Use normalized independent queue selection; no entity-only count drift. |
| operations/apps/core/finding_actions.py | Action metadata, eligible types, scope/permission/reason | Preserve registered actions; same-finding-type bulk restriction, mixed eligible Pause/Resume and explicit publisher/client scope. |
| operations/apps/core/finding_registry.py | Names/category/group/order and rule validation | Remains taxonomy authority. Add/validate subject and relationship rule configuration through existing admin surface, not a second Python mapping. |
| operations/apps/core/finding_state_checks.py | Read-only drift history page | Retain technical diagnostics; show common finding identity safely; no operator Readiness dependency. |
| operations/apps/core/finding_types_admin.py | Registry edits, audit/invalidation and May alert | Subject-kind/relationship validation and graph/rule refresh must be enforced on change; retain May alert control and permissions. |
| operations/apps/core/identity_actions.py | Recorded merge/separate/split/in-use/client operations | Keep exact case scope and SQL functions; accepted identity consolidation coordinated with PLAN-004, not an unrelated rewrite. |
| operations/apps/core/models.py | Finding/AdminFinding/read model/state/domain models | Extend existing Finding; align actual uniqueness and composite FKs; legacy admin projection unmanaged/read-only; preserve source/candidate models. |
| operations/apps/core/remote_access_approval.py | Product/client authorization writes | Keep separate from software approval; explicit broader all-client scope and audit. |
| operations/apps/core/software_decision_actions.py | Existing product/publisher decisions and prompt closure | Preserve existing decision scopes, reasons and strict installation coverage; common finding identity and consolidated prompt manifest. |
| operations/apps/core/software_review.py | Product review evidence/description | Full uncovered case population and scope; no partial OS-filtered approval case or hidden publisher inheritance. |
| operations/apps/core/templatetags/human_labels.py | Finding condition/evidence labels | Registry names remain authority; no action words in titles or false missing-agent claims. Related evidence stays in review context. |
| operations/apps/core/views.py | Queue/home/navigation, domain counts, candidate/admin assembly, reviews/actions/CSV | Extract common issue_selection/read adapter and hydrate selected rows only. Route home, CSV, client/Computer/source/admin totals through consistent scoped populations. Preserve unrelated dirty edits. |
| shared/software_settings.py | Rare/non-approved policy labels/switches and close limits | Retain settings compatibility until conversion; merge policy switches explicitly, not by silently dropping an operator-disabled rule. |

### Large-view functions requiring explicit request/action coverage

The views.py audit included findings_queue, home, org_index, device_detail,
_affected_device_rows, state/covered/critical helpers, finding review/refresh/
pause/exclude/bulk handlers, retirement and Hudu queueing, software page/detail,
patching_queue, client_mappings, inventory_clients, Admin Health presentation/
counts/actions, inventory source issue counts, mapping attach/resolve, device
merge, admin overview/data and notification configuration readers. Nested row
formatters are not independent population authorities.

## Additional indirect and presentation surfaces

| Surface | Treatment |
| --- | --- |
| shared/conditions/contracts.py | Preserve Condition.identity hash inputs; accept stored identity from common adapter. row_kind remains legacy namespace, not physical table selection. |
| shared/conditions/engine.py and policy.py | Preserve evidence/execution/clearing guards; no accidental state-machine rewrite to remove a UI column. Review configured type changes separately. |
| operations/apps/core/conditions/operator.py and report.py | Readiness labels remain diagnostic where needed; queue no longer exposes generic buckets. Common read input must retain precise scope and state meaning. |
| operations/config/urls.py | Retain issue/review/Admin legacy references and validated return routing; add only scoped selection parameters/handlers needed by accepted behavior. |
| operations/templates/findings_queue.html | Replace separate result sections with bounded grouped/Flat rendering, severity/count links, page/all selection and registered actions. No general row expansion. |
| operations/templates/finding_review.html | Prefer domain review destinations and restoration of queue scope; retain safe fallback evidence. |
| operations/templates/home.html, admin_settings.html, findings_admin_health.html | Match exact queue populations and link scope; Admin Health remains diagnostics/domain resolution, not a second independent backlog. Finding types link stays discoverable. |
| operations/templates/finding_types.html, finding_state_checks.html, admin/core/conditionpolicyversion/review.html | Keep configuration, audit and technical diagnostics aligned; avoid duplicate rule authorities. |
| operations/templates/software_policy_config.html, software review/detail and identity/client templates | Preserve type settings, helper evidence, decision scopes and safe domain operations while adapting common issue links. |
| operations/config/settings/base.py, prod.py and tenant middleware | ATOMIC_REQUESTS is already enabled; explicitly verify tenant/request snapshot behavior and background writer context. |
| operations/Dockerfile, ingest/Dockerfile, docker-compose.yml, operations/entrypoint.sh | Both images already copy shared and service code. Startup applies migrations; independent service restart is not writer quiescence. Review maintenance/release bundle. |
| ingest/main.py and ingest/jobs_worker.py | Add the common-schema admission check before starting producer/notifier/source-action work; existing early HTTP health is not permission to admit work before the contract is ready. |
| tests in ingest/tests and operations/apps/core/tests | PostgreSQL role/trigger/identity/cross-tenant tests plus request/browser/count/action acceptance in technical design; existing source-text tests alone are insufficient. |
| sql/migrations and legacy dashboard definitions | Do not edit old migrations. Retired ninja_agent_compliance schemas are historical, not a new runtime dependency. External saved SQL/Metabase references need authorized inventory before retirement. |
| change_history_registry and generic history/computer-history readers | Soft table/key lineage is not visible as an FK. Preserve legacy labels/aliases and distinguish storage-import events from world changes. |

## Cutover access inventory

Static AST inventory of direct `Finding.objects` / `AdminFinding.objects`
querysets (runtime Python; migrations/tests excluded), cross-checked against the
large-view function audit above. This classifies the current ORM surface. Raw
SQL/consumer coverage remains in the runtime ledger and external-consumer gate.

| Current ORM access | Call sites | Slice 1 treatment |
| --- | --- | --- |
| Entity finding reads for counts, filters, context | `context_processors.brand`; `client_workspace._issue_rollup`; `views.home`, `org_index`, `device_detail`, `_condition_operator_states`, `_software_page_data`, `software_detail`, `patching_queue`, `inventory_clients`, `_operations_admin_overview_snapshot`, `admin_data` | Entity-only adapter applies `condition_namespace='entity'` centrally, including counts and subqueries. Preserve current entity-only population. |
| Entity finding details and action targets | `capability_review_actions.decide_capability`; `identity_actions.run_identity_action`; `remote_access_approval.approve_remote_access`; `software_decision_actions.decide_software`; `views.finding_refresh`, `finding_reviewed_distinct`, `finding_review`, `finding_acknowledge`, `finding_resolve`, `finding_snooze`, `finding_suppress`, `findings_bulk_action`, `_retire_selected_computers`, `_queue_selected_hudu_archives` | Entity-only adapter for target lookup. Before mutation/queueing, check live relationships and exact contract generation; preserve permission, type, eligibility and exact-target checks. |
| Entity queue/CSV reads | `views.findings_queue` initial queryset, fleet-policy subset, grouped row set and `_findings_csv_response` | Keep entity namespace filter in slice 1. Do not union/import admin rows until slice 2. |
| Admin finding counts/details | `views.home`, `client_mappings`, `findings_queue` admin result/count, `findings_admin_health`, `_admin_health_system_findings`, `admin_data`; `conditions.reader` comparison snapshot | Read-only tenant-scoped compatibility view over admin namespace. Preserve Admin Health and action pages; check version/relationship at their action boundaries. |

This covers every direct runtime ORM queryset found by AST scan. Slice 1
eliminates direct `Finding.objects` reads outside the entity adapter and direct
`AdminFinding.objects` reads outside the compatibility adapter. Raw SQL writers
and reads are separately enumerated by the runtime ledger and must be routed
through the same adapters or common DB contract. Exact-set assertions cover both
adapters, home/domain counters, queue rows and exports, then assert disjointness
and union conservation.

## Process and contract-version inventory

| Process / entrypoint | Current admission point | Required contract behavior |
| --- | --- | --- |
| Operations web | `operations/entrypoint.sh` applies migrations before Gunicorn | Check exact contract after migration and before Gunicorn accepts traffic. The web binary reads and writes findings, so it requires the exact generation. |
| Ingest scheduler/API (`ninja_ingest`) | `ingest/main.py:main` binds liveness first, then initializes DB, migrates, registers schedules, starts scheduler and sets `_READY` | Check exact generation after migration and before schedule reconciliation, catch-up or `_READY`. Keep liveness available while starting. Recheck at request/dispatch/write boundaries. |
| Jobs worker (`ninja_ingest`) | `ingest/jobs_worker.py:run` initializes DB then registers/replays/reconciles before ready/dispatch | Check exact generation before replay or claim/admission, then before every claim and child side effect. A stale worker must not perform recovery against a newer schema. |
| Notification dispatch/digest | Ingest scheduler routes and Jobs definitions (`shared/jobs_registry.py`, `ingest/operator_job_queue.py`); `ingest/notifications.py` and `notifications_digest.py` send | Exact-generation action check at delivery. Recheck `may_notify`, live relation, rule, cooldown/event state immediately before send. Covers suppresses dispatcher and digest unless a reviewed rule explicitly exempts an effect. |
| Source-action worker | Jobs `source-actions` handler calls `ingest/source_actions.py:process_pending` | Exact-generation check before claim and final external mutation; recheck permission, exact target, `may_execute`, live relation and request token before archive. |
| Other finding producers | Ingest modules in runtime ledger; Operations action modules/views; SQL evaluator/trigger functions | Exact generation before process admission and DB boundary for each write. Do not rely on container startup alone; reject stale writers in SQL. |

All repository runtime binaries (Operations, ingest scheduler/API and Jobs
worker) require exact version 4/5/6 in M4/M5/M6 respectively; none is read-only
end-to-end. Migration-role execution is separate from runtime admission.
Current migrations grant direct DML on condition tables (0161) and
use purpose-specific `SECURITY DEFINER` writer functions (for example 0332).
The cutover must enumerate grants by relation/role and either revoke direct
graph-affecting DML or install trigger assertions that reject writes without a
prior tenant graph lock. Contract-version checks must also execute at DB write
and external-action boundaries because services can roll independently.

## Relationship action mapping inventory

| Relationship/effect | Existing authority path | Registered key and guard point |
| --- | --- | --- |
| Independent queue visibility | `operations.finding_state` and Issues selection | `finding.queue.select`; exclude Covered before count/page/export. Keep direct detail/review available. |
| Covers notification suppression | `ingest/notifications.py:dispatch` and `ingest/notifications_digest.py:send_digest`; both currently check `may_notify` | `notification.dispatch` and `notification.digest`; recheck live Covers at send time. A rule may explicitly exempt an effect. |
| Requires-gated condition action | Assessment policy and current `may_execute` paths, including source actions and Operations condition operator/report | `condition.execute` only where a rule names it. Review, refresh, investigate, acknowledge, resolve, pause/resume and prerequisite repair stay available by default. |
| Hudu archive mutation | UI action `archive_hudu_assets` queues backend request key `archive_hudu_asset`; `ingest/source_actions.py` checks exact IDs and `may_execute` | `source.archive_hudu_asset`; check at request, claim and external call. Keep UI and backend identifiers mapped to one registered effect. |
| Other registered UI actions | `FINDING_ACTIONS` in `operations/apps/core/finding_actions.py`; bulk/domain handlers | Keys: `retire_computers`, `merge_computers`, `confirm_computers_separate`, `split_computer_records`, `confirm_computers_in_use`, `move_computer_client`, `keep_computer_client`, `computer_client_source_wrong`, `approve_remote_access_all`, `approve_remote_access_client`, `software_approve_title`, `software_approve_publisher`, `software_reject`, `software_reject_publisher`, `software_investigate`, `software_investigate_publisher`, `capability_confirm`, `capability_reject`. No relationship gates these implicitly; a reviewed rule must register a specific effect. |
| Generic handling endpoints | `views.finding_acknowledge`, `finding_resolve`, `finding_snooze`, `finding_suppress`; pause/resume and refresh routes | Handling/review actions are not `condition.execute`; keep available on related findings unless a later explicit rule names one. |

Action keys are closed registry values, not arbitrary SQL or type-name branches.
Before migration design, seed each current relationship rule with scope,
satisfaction predicate, notification effects and gated action keys. Convert
`finding_types.covered_by` into Covers rules and exact Job run/dependency
closures from run-scoped producer evidence. Do not infer Requires from current
assessment `blocked` status alone.

## Database objects verified from current catalog

Read-only repeatable-read tenant-1 check at 2026-10-27 18:08 UTC. Current catalog
shows these 13 operations functions matching finding/state/row-kind/action refs:

- compute_finding_state; refresh_finding_state; touch_finding_state.
- finding_state_after_assessments; finding_state_after_assessment_update;
  finding_state_after_participants; finding_state_after_findings_insert;
  finding_state_after_finding_change.
- reconcile_condition_participants; device_requirement_state_disagreements.
- merge_computers; split_computer_merge; move_computer_to_client.

Replace state functions/triggers and participant namespace resolution in M3;
verify requirement drift and Computer mutation functions against the preserved
subject/ownership contract. Do not change their domain algorithms incidentally.
Two directly matching views: v_issue_findings and v_condition_assessment_current.
The former becomes a single-ledger projection; the latter retains policy/digest
freshness and alias-compatible identity. Current direct finding FKs are from
finding_state and source_action_requests; add tenant-safe composite enforcement.
Generic SQL and history may contain soft references; catalog matching is not
proof of every indirect consumer.

Historical migration sources of runtime rules: 0160–0166/0169/0203–0204 for
source actions and conditions, 0295–0304 for registry/state, 0306/0314/0319 for
history, 0308–0311 for Computer actions, 0332–0333 for requirement verdicts,
0340 for client ownership, and 0352–0353 for union view/exact duplicate closure.
Implement replacements in new migrations; never edit those old migrations.

## Alertability review

The following 21 types were true in the checked registry. M1–M4 preserve all
flags; no delivery is enabled. User approved the M5 exception:
device_unenrolled true → false when changed into an inventory/lifecycle review,
consistent with the principle that decision requests do not alert. M5 implements
this semantic change with a reviewed manifest. Other currently false types,
merged software approval and unified identity review remain false.
Full 71-type current/proposed matrix follows in the generated registry appendix.

| Current eligible type | M1–M4 | Approved M5 behavior |
| --- | --- | --- |
| device_never_patched | Keep true | Keep true |
| device_unenrolled | Keep true | Set false for approved inventory/lifecycle-review meaning |
| eol_runtime | Keep true | Keep true |
| install_path_suspicious | Keep true | Keep true |
| jobs_queue_backlog | Keep true | Keep true |
| jobs_registry_mismatch | Keep true | Keep true |
| jobs_repeated_failure | Keep true | Keep true for independently eligible incident |
| jobs_required_disabled | Keep true | Keep true |
| jobs_schedule_failure | Keep true | Keep true for independently eligible incident |
| jobs_timeout | Keep true | Keep true for independently eligible incident |
| missing_required_platform | Keep true | Keep true; confirmed security absence follows reviewed severity policy |
| patch_approval_backlog | Keep true | Keep true |
| patch_failing_repeatedly | Keep true | Keep true |
| rejected_software_installed | Keep true | Keep true |
| source_failure | Keep true | Keep true for independently eligible incident |
| stale_required_platform | Keep true | Keep true; does not prove protection absent |
| unauthorized_av | Keep true | Keep true |
| unauthorized_remote_access | Keep true | Keep true |
| unauthorized_rmm | Keep true | Keep true |
| vulnerable_software | Keep true | Keep true |
| windows_servicing_eol | Keep true | Keep true |

## Audit conclusions and explicit limits

Consolidation is justified by actual split readers/writers, lost admin context
and differing state/action paths. Keep it limited to one store/contract and
approved semantic conversions; do not modernize every domain model at once.

Zero UUID and live condition-key collisions were observed under tenant-1 RLS;
a query without an explicit tenant predicate is still RLS-scoped and is not an
all-tenant preflight. Admin subject shapes included platform-only and historical
hostname contexts, so incomplete subjects must be retained safely rather than
guessed. Actual live index predicates, not old ORM declarations, informed the
proposed uniqueness contract.

Not yet performed: final migration-code review/rehearsal, all-tenant identity
preflight, external saved-query audit, safe recovery rehearsal, browser/mobile
and latency tests. These are execution/release gates, not invented successful
validation. No runtime/source data or release metadata was changed.

## Registry appendix

The matrix below is populated from the same read-only registry snapshot.

| Registered type | Current | Proposed after semantic conversion | Reason |
| --- | --- | --- | --- |
| archived_but_reporting | False | False | Keep off |
| capability_review_candidate | False | False | Keep off |
| change_history_unclassified | False | False | Keep off |
| client_link_collision | False | False | Keep off |
| client_name_conflict | False | False | Keep off |
| client_source_group_merge | False | False | Keep off |
| client_unattached_group | False | False | Keep off |
| cmdb_asset_stale | False | False | Keep off |
| cmdb_link_incorrect | False | False | Keep off |
| computer_client_conflict | False | False | Keep off |
| computer_name_collision | False | False | Keep off |
| computer_name_differs_in_source | False | False | Keep off |
| cross_client_conflict | False | False | Keep off |
| cross_client_serial | False | False | Keep off |
| device_long_offline | False | False | Keep off |
| device_missing_from_source | False | False | Keep off |
| device_never_patched | True | True | Preserve eligibility; independent-condition guards apply |
| device_offline | False | False | Keep off |
| device_role_conflict | False | False | Keep off |
| device_source_record_withdrawn | False | False | Keep off |
| device_stale_data | False | False | Keep off |
| device_unenrolled | True | False (approved) | Inventory/lifecycle decision meaning |
| duplicate_device_records | False | False | Keep off |
| duplicate_platform_record | False | False | Keep off |
| eol_runtime | True | True | Preserve eligibility; independent-condition guards apply |
| identity_conflict | False | False | Keep off |
| identity_resolution_pending | False | False | Keep off |
| install_path_suspicious | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_queue_backlog | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_registry_mismatch | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_repeated_failure | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_required_disabled | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_schedule_failure | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_timeout | True | True | Preserve eligibility; independent-condition guards apply |
| jobs_unmet_dependency | False | False | Keep off |
| known_malicious_hint | False | False | Keep off |
| lifecycle_reported_state_conflict | False | False | Keep off |
| lifecycle_unknown_reported_state | False | False | Keep off |
| missing_required_platform | True | True | Preserve eligibility; independent-condition guards apply |
| multi_av_conflict | False | False | Keep off |
| os_unknown_coverage | False | False | Keep off |
| patch_approval_backlog | True | True | Preserve eligibility; independent-condition guards apply |
| patch_failing_repeatedly | True | True | Preserve eligibility; independent-condition guards apply |
| patching_stalled | False | False | Keep off |
| placeholder_mac | False | False | Keep off |
| placeholder_serial | False | False | Keep off |
| rare_recent | False | False | Consolidated into approval case; legacy history retained |
| reboot_pending | False | False | Keep off |
| rejected_software_installed | True | True | Preserve eligibility; independent-condition guards apply |
| shared_serial | False | False | Keep off |
| software_inventory_held | False | False | Keep off |
| software_queue_stalled | False | False | Keep off |
| source_failure | True | True | Preserve eligibility; independent-condition guards apply |
| source_name_kind_unclassified | False | False | Keep off |
| stale_collector_binding | False | False | Keep off |
| stale_required_platform | True | True | Preserve eligibility; independent-condition guards apply |
| suspicious_name | False | False | Keep off |
| two_machines_on_one_computer | False | False | Keep off |
| unauthorized_av | True | True | Preserve eligibility; independent-condition guards apply |
| unauthorized_remote_access | True | True | Preserve eligibility; independent-condition guards apply |
| unauthorized_rmm | True | True | Preserve eligibility; independent-condition guards apply |
| unintegrated_source_observed | False | False | Keep off |
| unlinked_external_identity | False | False | Keep off |
| unmapped_node_class | False | False | Keep off |
| unmatched_source_group | False | False | Keep off |
| unnamed_source_group | False | False | Keep off |
| vulnerable_software | True | True | Preserve eligibility; independent-condition guards apply |
| whitelist_suggestion | False | False | Canonical approval case; display name changes |
| windows_servicing_approaching_eol | False | False | Keep off |
| windows_servicing_eol | True | True | Preserve eligibility; independent-condition guards apply |
| windows_servicing_unknown | False | False | Keep off |
