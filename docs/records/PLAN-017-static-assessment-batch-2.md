# PLAN-017 — Phase 1 second static batch

Date: 2026-10-25. Status: local static work in progress; Phase 1 exit gate
not met. Read with the [assessment](PLAN-017-static-assessment.md) and
[charter](../plans/PLAN-017-consolidated-data-architecture-review-draft.md).
This batch follows R09 → R03/R04 → R02/R06, as requested. No application
code was imported or executed; no database/container/service, production,
commit or push action was performed.

## Baseline and preservation

HEAD on entry is `0c812db74e9a398fbe1f32a80db85c69f216f023`.
The existing inventory checker reports changed HEAD relative to its original
`be55a72`, but zero changed/missing/added source files. The preserved manifest
therefore remains a valid content baseline for these local traces. Neither
HEAD nor local files establish deployed definitions or schedules.

All six existing files in `docs/records/PLAN-017/` are left unchanged, including
the builder, manifest, recheck, routing CSV and both large lexical CSVs.
No inventory regeneration or repinning is performed. At any later commit
proposal, explicitly flag `object-occurrences.csv` and
`python-definitions.csv` as regenerable candidates to leave out; the user
has made no inclusion/exclusion decision yet. No commit is proposed now.

## R09 — Forward declarations, ORM, indexes and triggers

The initial lexical scan mixed forward/reverse SQL, fixtures and comments.
For this batch, a read-only Python AST walk selected each
`Migration.operations` list, the first argument of each `RunSQL`, and only
`database_operations` inside `SeparateDatabaseAndState`. It inspected
`execute` arguments in the forward `RunPython` callable. A restricted literal
resolver handled constants, lists, concatenation and literal string
replace/format/join; it did not import migration modules or call application
functions. Root SQL migration files were read separately in filename order.
This is a forward declaration inventory, **not a migration-state simulator**:
conditional SQL, function-body DDL, dynamic catalog loops, renamed/dropped
objects, implicit indexes/FKs and cross-runner order still need reconciliation.

| Static inventory unit | Count and interpretation |
| --- | --- |
| Django migration files | 329 numbered files, not 343 contiguous numbers; gaps in numbering are not missing migrations by themselves. |
| Ingest SQL migration files | 115 files, including filename 116; filename order is the ingest runner's order. |
| Selected operation sites | 278 RunSQL, 102 RunPython, 108 CreateModel, 93 AddField, 97 AddConstraint, 42 AddIndex, 25 AlterField, 17 SeparateDatabaseAndState, plus removals/options/rename. State-only operations were excluded from this database-operation count. |
| Resolved SQL fragments | 565 fragments including the 115 ingest SQL files; fragments can contain many statements and conditional branches. |
| CREATE declaration occurrences in resolved fragments | 121 TABLE, 310 INDEX, 85 UNIQUE INDEX, 210 FUNCTION, 58 MATERIALIZED VIEW, 146 VIEW, 39 TRIGGER, 2 CONSTRAINT TRIGGER. These include replacement/helper/guarded DDL, not live object counts. |
| Distinct names per kind in that partial extraction | 121 table, 198 ordinary-index, 52 unique-index, 150 function, 29 materialized-view, 75 view, 38 trigger, 2 constraint-trigger names. Names may be unqualified; overloaded functions and same-named triggers are not distinct physical-object counts. |
| Core model declarations | 112 explicit `Meta.db_table` mappings: 102 managed, 10 unmanaged; 63 explicit Meta Index, 87 UniqueConstraint, 21 CheckConstraint sites. Field-level PK/unique/db_index/FK indexes and inherited metadata are additional. |
| Unresolved expressions in literal extraction | 11 RunSQL argument sites and 24 RunPython execute sites. They have explicit destinations below; none is silently treated as no SQL. |

Dependency inspection found local dependency targets present where literal
tuples could be resolved. Migration 0046 also uses
`migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, so a literal-only
resolver cannot validate that external edge. No Django graph loader, migration
plan or applied-migration ledger was executed. The two migration runners both
touch Operations objects; numeric filename comparison across them is not a
valid global execution order.

### Imported/generated forward SQL destinations

| Files or family | Confirmed construction and required interpretation |
| --- | --- |
| 0027 and 0029 | RLS SQL is generated for local table lists. Inspect their loops and grants rather than dropping these operations from scope. |
| 0098 | Imports 0077's forward SQL and replaces the device-health presence predicate. The imported body recreates presence, session, source-health and v_device definitions; reverse text is not the effective forward definition. |
| 0104, 0105, 0106 | Each imports 0103's current PROJECTOR_SQL. Migration labels describe historical fixes, but the referenced file bytes determine the SQL on a fresh replay. |
| 0108 | Also imports 0103's claim projector, alongside its own effective-projector/trigger/privilege SQL. |
| 0114 | Imports PROJECTOR_SQL from 0111 to replace relationship/candidate projection. |
| 0279 | Imports 0272's workflow dependency function and substitutes its successor/supersession matching clause. |
| 0281 | Imports 0261 dispatcher SQL, applies an asserted sequence of literal replacements for contained-holder wait reasons. |
| 0291 | Generates an alertable finding-type UPDATE from a literal name list. This is data registration, not a missing object definition. |
| 0006/0014/0016/0018/0019/0020/0021/0022/0023/0036/0040/0066 RunPython loops | The 24 unresolved execute sites are chiefly per-role/table RLS/grants. Preserve loops' table/role sets and vendor guards. Exact catalog outcomes require later reconciliation. |

These constructions are code-confirmed by reading their source; this batch
does not execute their assertions, imports or SQL substitutions. Current
definition manifests must retain both the importing migration and original
body/replacement provenance. A fresh database can therefore use a later
shared body while an already-migrated database retains an earlier installed
body; this is a reconciliation risk to investigate, not proof of deployed drift.

### Contract/object ownership and migration chain

| Object family | Forward definition/owner/consumer evidence | Remaining reconciliation |
| --- | --- | --- |
| Canonical clients/devices/entities | 0101 anchor/link kernel; 0120 makes entity anchors required; Python resolver creates Computer anchor inline; 0342 creates a provisional client and matching anchor in one SQL function | Cross-tenant FKs, client moves and entity scope updates; not every current device/client field is represented by the current ORM. |
| Observation current/history/run | 0063/0064 current/history introduction, 0095 expand and 0096 stable identity cutover, 0097 daily presence, 0327 history record index | Forward constraints and privileges versus all writers and retention; old binding-key and stable-instance-key uniqueness coexist. |
| Daily presence | 0097 creates source_record_seen_daily outside ORM: PK tenant/source-record/day, BRIN day index, RESTRICT references to current row and first snapshot run, paired backfill provenance check | This is a concrete reference-protection dependency. Any disposal design must account for it, not apply a universal age cutoff across current/run/presence. |
| Links and link history | 0101 kernel; 0121/0123 retire legacy link tables behind read views; 0176 replaces link sync; 0315/0317 move/close link history during merge/split | Reconstruct the latest full chain before declaring 0101 alone authoritative. Registry/ADR ownership stays with identity plans. |
| Claim projection | 0102 ORM claim/config stores; 0103 SQL constraints/RLS/projector; 0104–0106 and 0108 import its body | Projection change detection scans observation/state signatures; it is not a dedicated source dirty-key queue. Config-only invalidation still needs complete writer tracing. |
| Effective values | 0107/0109 model stores; 0108 SQL composite FKs, decisions/dirty triggers, effective selection and support/conflict writes | Verify time/policy/definition invalidation, replay and sole-writer privileges. |
| Relationships/source events | 0110/0112 model stores; 0111 typed/scope triggers and projectors; 0113 history security; 0114 imported fix; 0115 restricted role cutover | Protect event identity and immutable source fields; validate every scoped/global endpoint and automatic relationship projection. |
| Effective readers and matviews | 0061 coordinator; 0098 imported presence chain; 0100 generic Ninja/software readers; 0121 and 0134 replace v_device; 0122 view DML revocation; 0124 legacy matview drops; 0334 safe observation metadata | Last matching CREATE in a lexical scan is insufficient: imported text, dependent drop/recreate, root SQL and dynamic grants also matter. |
| Change history and identity operations | 0306 registry-driven change trigger, 0308 merge/split relation, 0315/0317 link movement/history, 0319 audit bridge, 0328 name guards/writer | Audit inverse-action references and retention; dynamic per-table change triggers must be expanded from registrations. |
| Findings/requirements | 0297 attention replaced by 0301 finding_state and 0302 update filtering, 0303 drops old attention triggers; 0332/0333 stored verdicts/applicability | Do not count both attention and replacement finding-state paths as current. PLAN-014 owns applicability changes. |
| Jobs and queues | 0183 definition/request immutability, claim/dependency/recovery/capacity migrations through 0284, later schedule/resource/replay patches | Actual job SQL/state, enabled schedules and catalog need authorized reconciliation; shared registry declarations are not proof of runtime configuration. |
| Software/reference | Root SQL corpus and software relationships/indexes; 0250 reclassification targets, 0285 inventory devices, 0286/0293 reader changes; SQL 112/114 exposure; SQL 115 queue retirement; SQL 116 active lookup indexes | Native listing/canonical/reference scopes differ; reconstruct installed definitions and consumers before removing copies or indexes. |

### Key index and preventive-constraint contracts

| Mechanism | Declared grain/order or enforcement | Assessment consequence |
| --- | --- | --- |
| uq_obs_current_stable_identity | Tenant/instance/namespace/parent namespace/parent ID/external ID | Prevents duplicate current identity on that key, not duplicate machines or arbitrary binding/type identities. |
| uq_obs_hist_open_stable_identity | Same stable tuple, partial on effective_to IS NULL | Prevents two open intervals; does not alone prevent all closed-interval overlap or prove current/history parity. |
| idx_obs_current_observed; idx_obs_current_active | Tenant/observed_at and tenant/active/entity_type | Declared readers/heartbeat updates need comparison with the source-record tenant/last_seen/UUID sort; no live index or HOT-cost conclusion. |
| uq_entity_source_links_stable; uq_entity_source_link_history_open | Stable identity current/open membership keys; positive-window check in history | Preserves membership grain; does not prove every manual move closes matching history. 0317 specifically repairs that boundary. |
| idx_entity_link_hist_entity; idx_entity_link_hist_retention | Tenant/entity/effective_from; tenant/effective_to | Timeline/expiry purposes distinct; retain reference/undo rationale before physical simplification. |
| uq_attr_claim_current_member; uq_attr_claim_history_open | Tenant/observation/attribute/member; one open interval per tenant/current claim | Per-source assertion/member grain differs from one effective value per entity/attribute. These copies cannot be labeled duplicates only from row counts. |
| uq_attr_effective_dirty; idx_attr_effective_dirty_queue | Tenant/entity/attribute coalescing; queued_at/id order | One desired-state work key, not an immutable-event log. Compare queue coalescing with replay/concurrent generation requirements. |
| Composite FKs in 0108 and 0111 | Tenant/entity/class and typed definition/member/actor references; deferred constraints, RESTRICT/CASCADE according to dependency | Actual preventive mechanisms exist beyond Python model FKs; confirm latest SQL and runtime writers before global scope claims. |
| source_record_seen_daily PK/BRIN/FKs | Tenant/source-record/day; BRIN rollup_day; RESTRICT current/run references | Bounded row duplicates per day, not a byte bound, continuous presence, or unrestricted run-log cleanup. |
| uq_source_events_external_id | Tenant/instance/external event ID; parent identity check and processing/time indexes | Dedup scope is source-instance specific; source-ID reuse and event retention must preserve intended replay horizon. |
| computer_merges_one_open_per_absorbed | Partial unique open merge relation; 0308 deferred merge constraint trigger | Maintains recorded merge relationship; split means membership/provenance restoration, not all intervening state rollback. |

### Trigger and privilege inventory destinations

| Family | Explicit sites and meaning | Scope not yet proved |
| --- | --- | --- |
| Attribute decisions | 0108 validate_attribute_decision_member; audit_and_queue_attribute_decision and member trigger | Direct decisions/members queue entity/attribute work transactionally. Config/reference/time-only invalidation needs separate evidence. |
| Relationship/source event validation | 0111 validate_relationship_evidence/decision/dirty/current; queue_relationship_evidence; audit_and_queue_relationship_decision; protect_source_event_immutable | Type/cardinality/scope/immutability protection for these stores, not proof every reader is tenant safe. |
| OS identity | 0153 validate_os_installation_entity | Per-entity installation scope; parent/identity evolution unresolved. |
| Condition/Jobs immutability | 0161 policy/version immutable; 0183 definition/request/schedule-event immutable; 0219 domain-attempt immutable | Which metadata is protected and retained, and permitted terminal transitions, remain R01/R05. |
| Jobs lifecycle | 0227 schedule-terminal trigger, 0231 definition priority, 0255 waiting-state trigger, 0271 contained-capacity release | Dynamic dispatcher and schedule authority still need exact SQL reconciliation. |
| Finding state | 0301 assessment/participant/finding triggers, revised by 0302; 0303 removes old attention triggers | Trigger-maintained current state includes policy/time freshness calculations; time alone requires a reader/schedule contract. |
| Change actions | 0306 register_change_history dynamically installs record_change per registered table; 0319 audit_log_into_change_history | One lexical trigger name can represent many installed table triggers; expand current registry before counting or disposing action history. |
| Naming/merge | 0308 require_merge_relation; 0328 devices_guard_computer_name and devices_named_at_commit | Name fields use controlled operations_naming writer/guards; do not infer the five other typed cache fields have the same enforced sole-writer mechanism. |
| Read-model DML | 0122 loops over views/matviews and revokes DML for runtime roles; 0334 explicitly revokes metadata-view DML | The sweep only covers objects present when it executes. Review later view creation/default privilege effects per object; no current privilege leak asserted here. |

## R03/R04 — First client and Computer publication order

1. Collection reads existing client links and matches existing Computers; a new
   source group can remain client-unassigned. Ninja includes staged organization
   container rows. The shared transaction writes source records, run membership
   and history before the collection's shared refresh.
2. Shared refresh synchronizes generic links from **currently assigned** identity,
   then claim/effective/candidate/OS/relationship projectors, then SQL derived
   readers. Generic projector failures are swallowed despite the docstring
   contract (F04). Batches commit independently and non-complete return states
   are not promoted to required-stage failure.
3. The identity-source workflow's next job is resolver (shared Jobs registry
   _WORKFLOW_SUCCESSORS). The durable handler runs main.run_identity_resolver_once:
   client resolution first, then Computer resolution/promotion. A new client's
   promotion occurs before loading the name index; 0342 creates its anchor and
   alias. The resolver's group attachment updates org/device observation
   client_id, allowing Computer promotion later in the same resolver job.
4. Client candidates are created/incremented after the pre-pass promotion
   attempt. A first-ever unseen candidate therefore cannot be promoted before
   it exists, and configured repeated-observation/evidence criteria can require
   later resolver runs. This is intentional identity policy, not automatically
   an S1 defect; S1 must state the supported first-visible guarantee.
5. Computer promotion creates the entity anchor and neutral typed cache fields,
   attaches observation device_id and names the Computer before commit.
   Migration 0120 enforces non-null anchors; 0328 enforces naming at commit.
   Attachment comments explicitly defer generic source links to link sync.
6. The same resolver then runs the device compatibility-cache projector, then
   typed facets. The cache projector reads effective attributes and generic
   links/type evidence. No direct generic link/claim/effective refresh call is
   present in the inspected promotion, naming or resolver path. Its optional
   post-resolution refresh updates presence and session, not the generic stages.
   The successor is platform-evaluate.
7. Consequently, inline anchor creation resolves the old null-anchor gap, but
   does **not** prove first-pass effective/cache publication for a just-created
   Computer. A generic projection before resolver-created attachment cannot
   have consumed that new attachment. The next collection/shared refresh and
   resolver may converge it; queue scheduling/other writers need reconciliation
   before asserting exactly one cycle of lag or a measured user-visible defect.

This deepens F04 and S1/S8/S10 without choosing whether the synchronous
publication contract or the current asynchronous rollout is correct.
A bounded Phase 2 trace should use a new group/client/Computer, distinguish
first evidence, accepted identity and published fields, and check job success
and retry generations at each boundary. It is not executed now.

Additional R04 correction: SQL 0103 builds candidate observation signatures
and compares projection_state; only effective projection drains a named
entity/attribute dirty queue. LIMIT caps accepted batch rows, not proven
total scanning/hashing work. Config/authority-policy/mapping versions are
not evident in the observation projection signature. Direct decision triggers
are confirmed; all config writers/admin hooks and time-driven invalidation
remain explicit unknowns rather than a proven absence.

## R02 — Narrowed F01 fetcher audit

| _FETCHERS platform | Complete/empty/partial mechanism in local source | F01 and follow-through |
| --- | --- | --- |
| SentinelOne | Agent pages follow nextCursor and HTTP failures raise; missing host/name normalization skips rows. Separately paged sites create container-only rows; their exceptions are logged and swallowed, retaining any earlier site pages. | Empty devices plus successful nonempty sites still reconcile. Fully empty normalized output skips reconciliation. Partial sites plus a nonempty overall result have no completeness marker (U02 below). Verify repeated cursor and malformed successful payloads. |
| ScreenConnect | One access-session response; deleted/ended sessions and missing/invalid names are omitted. Requires client configuration. No container-only row is emitted independently. | Zero surviving sessions yields [], including an empty/all-ended population. No paging/completeness envelope distinguishes limited/malformed success. Account for filtering/rejected rows before treating emptiness as complete absence. |
| LogMeIn | hostswithgroups response; one HTTP 429 retry, then HTTP failure raises. Groups emit independent container rows. Missing normalized host names are skipped. | Empty hosts with groups do not hit F01; empty hosts and groups do. Successful missing hosts/groups keys are interpreted as empty. hostStateChangeDate is still preferred for last_seen_at, a separate timestamp-meaning lead. |
| R-U-ON | Authenticated HTML/layout checks raise on recognized failures; parser reads list rows. Machine records are collected; process monitors pair into machine evidence; unsupported types are logged. Containers are derived from accepted machine groups, not an independent group census. | Zero accepted machines can yield [] even with parsed unsupported/unpaired records; R02 must distinguish intended filtering from authoritative empty snapshot. Contact remains null rather than guessing timezone from console text. |
| Hudu | Layout/asset page failures raise; a short page ends pagination; hitting the 400-page cap raises, protecting against that partial fetch. Excluded layouts are counted. No separate company-only enumeration. | No included assets yields [] and F01. HTTP-success malformed/missing assets shape can look empty. Archived/relayed evidence is kept in canonical_extra; do not promote documentation to device-contact authority. |

SourceConfig exposes an is_partial_snapshot flag; the shared writer uses it.
These five fetchers return bare lists rather than a per-result acquired/
accepted/rejected/completeness receipt. The presence of that configuration
flag therefore does not itself classify individual failed/permission-limited/
malformed success responses.

**C2 source-guard correction, code-confirmed:** evaluator._source_failure_guard
calls source_health.collection_problems. The latter queries enabled bindings,
latest terminal source-refresh Jobs and latest source_refresh_outputs; it does
not query run_log. The only run_log SQL in evaluator is its evaluation receipt
INSERT. Empty fetch still writes ok=True/rows=0 in the collection run log.
The durable source-refresh handler then calls shared refresh and returns a
normal JobExecutionResult when no stage raises, so the analogous false-success
risk remains at that lifecycle/output boundary. The exact SQL publication
function and freshness/partial-output meanings still need a complete R01 trace.
This corrects the review's direct-reader premise without dismissing the defect.

**U02 — Optional site-page failure versus complete absence.** SentinelOne's
sites helper can return only a prefix after an exception, while the caller
continues without a partial marker. If earlier/current container rows exist
only for omitted empty sites, a subsequent nonempty shared complete run can
withdraw them. Agent-derived groups may preserve some containers, and the
intent may be best-effort site metadata; clarify that contract and trace
downstream group readers before grading a new finding. Code mechanism is
confirmed; source incidence and any deployed wrong withdrawal are unknown.
Next: R02 container-scope contract, then bounded partial-site experiment after
Phase 2 authorization. No source API is called.

## R06 — Software acquisition, publication and replay

Confirmed useful safeguards: software.pages carries an explicit final
completeness flag, remembers a previously reported total across an empty final
page, flags stalled offsets/cap, and HTTP errors propagate. apply commits
accepted installation additions/changes and title targets together; removals
require both complete listing and per-device hold policy. Device absence from
a listing preserves prior rows. fleet_check and device_refresh raise after
apply returns if the result is incomplete; accepted partial additions can
therefore be durable even though the owning job fails.

The software queue marks successful batch entries done before main's final
read-model refresh. A failed device_refresh does not contribute its material
counts to DrainResult, even if its partial apply committed. main refreshes
software title/safety views only when the current ApplyResult/DrainResult says
material_changed, then returns a material_change successor signal. These are
distinct from persistent software_reclassification_targets, which survive
apply and are consumed by successful software reconciliation.

### F06 — A retry need not republish already committed software changes

- Contract/criteria: R06/R01; A4/A10; S8/S10. Grade: code-confirmed conditional
  failure/retry path. Conditional severity: Medium for stale software readers;
  likelihood unknown; confidence high in commit/branch ordering, unverified
  for deployed result impact.
- Evidence: inventory.software.apply commits before fleet_check/device_refresh
  returns; main.run_software_fleet_check_once and run_software_queue_once call
  refresh_read_models only on new material change. That function publishes
  title and safety separately, then catalog, with additional EOL error logging.
  A failure after apply but before/during publication loses that call's result.
  An identical retry may report unchanged (or find no pending queue entries)
  and skip publication and its material_change successor signal.
- Affected consumers: software title/safety/catalog-derived readers and dependent
  findings timing. This is a publication/replay gap, not demonstrated loss of
  raw installations or all durable downstream demand.
- Competing explanation/mitigation: title targets are written transactionally
  with changes; separate scheduled classifier/full-fleet work and later source
  changes may reconcile findings. They do not by themselves prove a retry of
  these title/safety/catalog publication stages. Complete reader/refresh/schedule
  audit is required before claiming persistence duration or broader impact.
- Options: retain durable publication demand until all required readers publish,
  or make replay publish independently of a fresh mutation delta, or establish
  a bounded reconciliation guarantee with explicit success/freshness semantics.
  Compare cost and compatibility before choosing; no runtime fix authorized.
- Verification/owner: trace all refresh callers and target consumers, then
  synthetic failure after apply/between matviews/before catalog with identical
  retry and empty queue. Coordinate PLAN-002/005/007/software owners; completed
  PLAN-011 is lineage, not permission to reopen implementation.

Reference-feed paths also use MaterialCount/material_changed to admit
successors. Current NVD/CPE/KEV/EPSS and matcher paths were located, but API
cursor/refetch windows, reference-policy changes and loss of downstream demand
across their commit/finish boundary still need individual R06/R01 traces.
Read-only source acquisition alone does not prove publication replay safety.

## Coverage and next checkpoint

This batch advances S1 (first identity/publication), S3 (five fetchers),
S8/S10 (software and projector publication), S9/S12 (constraint/trigger
mechanisms), and S11 (decision triggers versus config/time invalidation).
It does not globally pass those scenarios or any A1–A10 criterion.

The Phase 1 gate remains open for: current forward object reconciliation across
both migration runners; complete index/trigger/default-grant and indirect reader
audit; policy/time/reference invalidation; remaining domain exceptions; lifecycle/
undo/disposal references; and cost evidence limits. D1–D5 still need exact SQL,
roles, bounds, tenant context, D4 request/export text and Claude review before
an approval request. D3 privileged integrity queries and D4 runtime timings must
name different execution roles. No diagnostic was run or approval requested.

Next static slice: reconcile R01 source-refresh output/terminal SQL with F01/F04,
trace R04 configuration/time invalidation and R06 persistent publication demand,
and complete per-domain current object/consumer/lifecycle destinations. Keep
R09 imported/dynamic and cross-runner uncertainties explicit. The first estimate
remains 10–22 engineer-days for remaining Phase 1 through Phase 5; re-estimate
after this reconciliation, and present it before proposing Phase 2.

## Core ORM storage mapping inventory

The following 112 rows enumerate explicit Meta.db_table mappings in
operations/apps/core/models.py at the preserved baseline. M/U denotes managed/
unmanaged; I/UQ/C counts explicit Meta indexes/unique/check constraints.
They are ORM declarations, not proof of current physical kinds or live index
counts. SQL-only stores (daily presence, Jobs, verdicts, reference corpora,
software installations and many others) are covered by the forward families
above and remain in the SQL reconciliation, not silently omitted because no
ORM class represents them.

| Model | db_table | M/U | I / UQ / C |
| --- | --- | --- | --- |
| Tenant | `tenants` | M | 0 / 0 / 0 |
| User | `users` | M | 0 / 0 / 0 |
| Source | `sources` | M | 0 / 0 / 0 |
| EntityClass | `entity_classes` | M | 0 / 0 / 0 |
| EntityClassScope | `entity_class_scopes` | M | 0 / 1 / 0 |
| Entity | `entities` | M | 1 / 2 / 1 |
| EntityType | `entity_types` | M | 0 / 0 / 0 |
| PlatformAlias | `platform_aliases` | M | 0 / 0 / 0 |
| Collector | `collectors` | M | 0 / 0 / 0 |
| FindingType | `finding_types` | M | 0 / 0 / 1 |
| ConditionPolicyVersion | `condition_policy_versions` | U | 0 / 0 / 0 |
| Client | `clients` | M | 0 / 1 / 0 |
| ClientSourceLink | `v_client_source_link` | U | 0 / 0 / 0 |
| ClientNameAlias | `client_name_aliases` | M | 0 / 1 / 0 |
| ClientOrgExclude | `client_org_excludes` | M | 0 / 0 / 0 |
| PlaceholderOrgName | `placeholder_org_names` | M | 0 / 1 / 0 |
| ClientCandidate | `client_candidates` | M | 0 / 1 / 0 |
| ClientPolicy | `client_policies` | M | 0 / 1 / 0 |
| OperatorDecisionDimension | `operator_decision_dimensions` | M | 0 / 0 / 0 |
| DeviceOperatorDecision | `device_operator_decisions` | M | 0 / 1 / 0 |
| Device | `devices` | M | 0 / 0 / 0 |
| OperatingSystemInstallation | `operating_system_installations` | M | 1 / 1 / 0 |
| OperatingSystemInstallationSourceIdentity | `operating_system_installation_source_identities` | M | 1 / 1 / 0 |
| DeviceSourceLink | `v_device_source_link` | U | 0 / 0 / 0 |
| Asset | `assets` | M | 3 / 1 / 0 |
| OSInstance | `os_instances` | M | 2 / 1 / 0 |
| AgentInstance | `agent_instances` | M | 3 / 1 / 0 |
| AssetFieldHistory | `asset_field_history` | M | 2 / 0 / 0 |
| OSInstanceFieldHistory | `os_instance_field_history` | M | 2 / 0 / 0 |
| AgentInstanceFieldHistory | `agent_instance_field_history` | M | 2 / 0 / 0 |
| PatchingScopeSignal | `patching_scope_signal` | M | 0 / 0 / 0 |
| PatchingScopeDefault | `patching_scope_default` | M | 0 / 0 / 0 |
| PatchingScopePolicyAllowlist | `patching_scope_policy_allowlist` | M | 0 / 0 / 0 |
| DevicePatchingOverride | `device_patching_override` | M | 0 / 0 / 0 |
| ClientUser | `client_users` | M | 0 / 0 / 0 |
| ClientUserLink | `client_user_links` | M | 0 / 1 / 0 |
| SourceInstance | `source_instances` | M | 0 / 0 / 0 |
| CollectorInstance | `collector_instances` | M | 0 / 1 / 0 |
| SourceBinding | `source_bindings` | M | 0 / 1 / 0 |
| EntitySourceLink | `entity_source_links` | M | 2 / 1 / 1 |
| EntitySourceLinkHistory | `entity_source_link_history` | M | 2 / 1 / 2 |
| EntityCandidate | `entity_candidates` | M | 1 / 1 / 1 |
| EntityCandidateEvent | `entity_candidate_events` | M | 1 / 0 / 0 |
| AttributeDefinition | `attribute_definitions` | M | 0 / 3 / 0 |
| SourceFieldMapping | `source_field_mappings` | M | 0 / 1 / 0 |
| SourceRecordLifecycleMapping | `source_record_lifecycle_mappings` | M | 0 / 1 / 0 |
| IdentityAuthorityPolicy | `identity_authority_policies` | M | 0 / 1 / 0 |
| IdentityMatchPolicy | `identity_match_policies` | M | 0 / 2 / 0 |
| AttributeAuthorityPolicy | `attribute_authority_policies` | M | 0 / 1 / 0 |
| EntityAttributeClaimCurrent | `entity_attribute_claim_current` | M | 2 / 2 / 2 |
| EntityAttributeClaimHistory | `entity_attribute_claim_history` | M | 2 / 1 / 1 |
| EntityAttributeWithheldCurrent | `entity_attribute_withheld_current` | M | 1 / 1 / 0 |
| EntityAttributeProjectionState | `entity_attribute_projection_state` | M | 1 / 1 / 0 |
| EntityAttributeDecisionCurrent | `entity_attribute_decision_current` | M | 1 / 2 / 1 |
| EntityAttributeDecisionMemberCurrent | `entity_attribute_decision_member_current` | M | 0 / 1 / 1 |
| EntityAttributeEffectiveDirty | `entity_attribute_effective_dirty` | M | 1 / 1 / 0 |
| EntityAttributeEffectiveCurrent | `entity_attribute_effective_current` | M | 1 / 2 / 1 |
| EntityAttributeEffectiveMemberCurrent | `entity_attribute_effective_member_current` | M | 0 / 2 / 1 |
| EntityAttributeEffectiveClaimSupport | `entity_attribute_effective_claim_support` | M | 0 / 1 / 0 |
| EntityAttributeConflictCurrent | `entity_attribute_conflict_current` | M | 1 / 2 / 1 |
| EntityAttributeConflictClaimSupport | `entity_attribute_conflict_claim_support` | M | 0 / 1 / 0 |
| RelationshipType | `relationship_types` | M | 0 / 0 / 0 |
| RelationshipAuthorityPolicy | `relationship_authority_policies` | M | 0 / 1 / 0 |
| EntityRelationshipEvidenceCurrent | `entity_relationship_evidence_current` | M | 1 / 2 / 2 |
| EntityRelationshipEvidenceHistory | `entity_relationship_evidence_history` | M | 2 / 1 / 1 |
| EntityRelationshipDecisionCurrent | `entity_relationship_decision_current` | M | 0 / 2 / 0 |
| EntityRelationshipDirty | `entity_relationship_dirty` | M | 1 / 1 / 0 |
| EntityRelationshipCurrent | `entity_relationships` | M | 1 / 2 / 0 |
| EntityRelationshipEvidenceSupport | `entity_relationship_evidence_support` | M | 0 / 1 / 0 |
| SourceEvent | `source_events` | M | 2 / 2 / 1 |
| EntityAttributeEffectiveEvidence | `v_entity_attribute_effective_current` | U | 0 / 0 / 0 |
| EntityAttributeClaimEvidence | `v_entity_attribute_claim_current` | U | 0 / 0 / 0 |
| EntityAttributeClaimStorageStatus | `v_entity_attribute_claim_storage_status` | U | 0 / 0 / 0 |
| EntityObservation | `entity_observations` | M | 3 / 1 / 0 |
| EntityObservationCurrent | `entity_observation_current` | M | 2 / 2 / 1 |
| EntityObservationHistory | `entity_observation_history` | M | 2 / 2 / 1 |
| ObservationSnapshotRun | `observation_snapshot_runs` | M | 2 / 2 / 0 |
| DeadLetterObservation | `dead_letter_observations` | M | 2 / 0 / 0 |
| SoftwareCatalog | `software_catalog` | M | 0 / 2 / 0 |
| SoftwareDecision | `software_decisions` | M | 0 / 6 / 1 |
| PublisherAlias | `publisher_aliases` | M | 0 / 1 / 0 |
| PublisherCategory | `publisher_categories` | M | 0 / 0 / 0 |
| IntelMatcherHint | `intel_matcher_hints` | M | 0 / 1 / 0 |
| EolProductMap | `eol_product_map` | M | 0 / 0 / 0 |
| SoftwareClassifierRule | `software_classifier_rules` | M | 0 / 1 / 0 |
| SoftwareSuggestionRule | `software_suggestion_rules` | M | 0 / 0 / 0 |
| MergeCandidate | `merge_candidates` | M | 1 / 1 / 0 |
| Finding | `findings` | M | 5 / 1 / 0 |
| RequirementProfile | `requirement_profiles` | M | 0 / 2 / 0 |
| Agent | `agents` | M | 0 / 0 / 0 |
| PlatformProductMap | `platform_product_map` | U | 0 / 0 / 0 |
| ProductAuthorization | `product_authorizations` | U | 0 / 0 / 0 |
| IdentityValueRejection | `identity_value_rejections` | U | 0 / 0 / 0 |
| OsGroupMapping | `os_group_mappings` | M | 0 / 0 / 0 |
| OsFamilyMapping | `os_family_mappings` | M | 0 / 0 / 0 |
| NodeClassMapping | `node_class_mappings` | M | 0 / 0 / 0 |
| RequirementProfileItem | `requirement_profile_items` | M | 0 / 1 / 0 |
| CoverageRequirement | `coverage_requirements` | M | 0 / 0 / 0 |
| AdminFinding | `admin_findings` | M | 1 / 1 / 0 |
| QueueRegistry | `queue_registry` | M | 0 / 0 / 0 |
| NotificationRule | `notification_rules` | M | 0 / 0 / 0 |
| NotificationState | `notification_state` | M | 0 / 1 / 0 |
| NotificationEvent | `notification_events` | M | 1 / 0 / 0 |
| EvaluatorConfig | `evaluator_config` | M | 0 / 1 / 0 |
| SuppressionRule | `suppression_rules` | M | 1 / 0 / 0 |
| NotificationRoute | `notification_routes` | M | 0 / 0 / 0 |
| Secret | `secrets` | M | 0 / 1 / 0 |
| AuditLog | `audit_log` | M | 2 / 0 / 0 |
| RunLog | `run_log` | M | 1 / 0 / 0 |
| UserGroup | `user_groups` | M | 0 / 1 / 0 |
| UserPermission | `user_permissions` | M | 0 / 1 / 0 |
| StoredFindingState | `finding_state` | U | 0 / 0 / 0 |


## Validation

Passed: 18-entry plan registry validator; scoped diff/whitespace checks;
assessment/batch/checkpoint local file links and line-anchor bounds; source AST
parsing during forward/ORM enumeration; zero changed pinned source files; and
byte-for-byte preservation of all six original evidence files. C1–C6 and the
Codex round 12 completion marker are present in the debate reply.

Global diff check still flags the unrelated Operations blueprint EOF blank
line at 718. The root blueprint already exceeded the repository workflow's
4,000-byte cap. Claude's shared-governance result is a separate validator;
this task does not claim that the repository workflow passed. No application
tests, Django graph loader, SQL execution or deployed-catalog validation is
claimed. No runtime file, production state, commit or push was changed by this
assessment.
