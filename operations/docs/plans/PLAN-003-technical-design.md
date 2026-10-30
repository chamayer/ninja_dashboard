# PLAN-003 — Unified findings technical design

Status: second-pass technical review incorporated, 2026-10-27. Design documentation only;
no runtime code, migrations, evaluator runs, source actions, commit or
deployment are authorized by this package. Baseline: HEAD `80557f6` plus the
pre-existing dirty worktree. Preserve unrelated changes, particularly views.py.

Contract: [current design](PLAN-003-current-design.md). Evidence and dependency
inventory: [consumer ledger](PLAN-003-consumer-ledger.md),
[finding review](PLAN-003-review-proposal.md). Proposed architecture record:
[ADR-0046](../decisions/0046-unified-findings-and-relationships.md).

## 1. Scope and implementation order

The worthwhile consolidation is one findings ledger, one state/relationship
contract and one queue selection pipeline. Keep existing domain workflows.
Storage conversion does not itself merge conditions, change severity, activate
alerts or repair unrelated identity/OS data. Those effects need their own
reviewed conversion manifests and tests. Do not combine every similar type.

Build in three bounded slices, with independently reviewed release gates:

1. **Common persistence and relationships:** expand existing findings; preserve
   identities; convert admin storage and its consumers; establish common state
   and typed Covers/Requires. Until slice 2, keep existing page assembly with
   namespace-disjoint adapters: every existing `Finding` read is routed through
   an entity-only adapter (`condition_namespace='entity'`); every legacy
   `AdminFinding` read is routed through the compatibility view, which exposes
   only the admin namespace. Preserve these adapters for dashboard/home,
   context processors, queue, domain counters, exports, and review links. New
   shared selection may query the full population only in slice 2. No other
   reader may query the unqualified unified population in this release.
2. **One queue and review routing:** replace separate result assembly with one
   selection contract; implement accepted grouping, counts, direct links,
   filters, selection and action behavior. Fix home mapping scope/count/link.
3. **Named semantic conversions:** software approval consolidation; proven
   root-incident consolidation; accepted per-source-group cases; inventory
   meaning of unenrolled and integration-gap review. Coordinate ADR-0043 with
   PLAN-004 rather than build a second identity algorithm. Each conversion
   must have an identity/disposition manifest and acceptance evidence.

An intermediate slice is not completion of PLAN-003. Report its remaining
behavior explicitly. Do not introduce a second permanent write path to enable
incremental releases. Candidate lifecycle and measured unrelated data cleanup
remain in PLAN-021 and their recorded backlog.

## 2. Existing schema facts that affect conversion

Read-only production catalog check: 2026-10-27 18:08 UTC, repeatable read,
transaction_read_only=on, tenant context 1. Catalog metadata and public registry
fields only. The ledger records objects and limitations.

- Finding uses UUID subject_id and typed subjects; AdminFinding uses arbitrary
  subject_ref JSON, different timestamp names, and no pause field.
- Actual active-key indexes include open, acknowledged, investigating and
  suppressed. Django's older model declarations omit some of these statuses.
  Align migration state with the real indexes; do not accidentally drop their
  episode-preservation semantics.
- Assessments/participants are keyed by tenant, row_kind, finding_id and
  participant identity; condition identity hashes include row_kind, type name
  and condition_key. Changing table alone must not recompute those identities.
- finding_state and source_action_requests currently FK directly to findings.
  Their old single-column FKs need tenant-safe composite enforcement.
- State triggers currently process entity assessments only. Admin rows need
  equivalent trigger coverage, not a special display fallback.
- Registry subject_scope is not authoritative conversion evidence: some Jobs
  and client/CMDB types declare device while stored subjects are different.

## 3. Common finding contract

Extend `operations.findings`, retaining its name, existing UUIDs, fields and
status values. Do not add a third authoritative ledger.

| Field/change | Contract |
| --- | --- |
| id, tenant_id, version, finding_type_id | Preserve existing values and tenant/version history. Add UNIQUE(tenant_id,id) for composite FKs. |
| subject_type, subject_id | Retain existing valid subjects; allow subject_id NULL only for validated structured non-UUID subjects. A native source/Job UUID is a mechanism reference, not a fabricated canonical entity. |
| subject_ref JSONB | Add, default {}. Structured natural references for groups, Jobs, queues and legacy context; UUID subjects can carry supporting provenance. Validate against registry-allowed subject kinds. |
| client_id | Set only from validated owned subject or explicit trusted scope. A tenant/global product issue is not an Unassigned-client Computer. Preserve existing Computer ownership semantics and client-move updates. |
| condition_namespace | Add immutable identity metadata, entity/admin for existing producers. This is not a table selector or operator filter; both use the same ledger and state path. Preserve namespace rather than renumber legacy assessments. |
| condition_identity | Add stable stored identity. Backfill using agreeing existing assessments or the frozen current hashing algorithm; reject ambiguous mappings. Do not recompute on display/type normalization. |
| condition_key | Preserve exact legacy bytes for storage conversion. Later semantic conversions use explicit aliases/mappings; mutable client labels are not a new condition identity. |
| episode_key | Add optional stable logical scope key for explicitly converted families, with a unique active tenant/key index. NULL for untouched legacy episodes. This permits one product approval case to retain its UUID/legacy key as rarity changes, rather than re-keying every old episode. |
| finding_details | Keep evidence JSON and closure reasons. Preserve original admin subject_ref separately when normalization adds a typed representation; never overwrite source history. |
| timestamps/status/handling | Preserve existing fields. Operator Open maps open/acknowledged/investigating, subject to pause. suppressed/wontfix remain retained closed decisions, not new Open work. |

Admin mapping: id/version/type/key/severity/status unchanged; details maps to
finding_details; first_detected_at → first_seen_at; last_detected_at → both
last_seen_at and last_detected_at; resolved_at → closed_at. Confidence stays
empty, owner/SLA/pause/review fields NULL unless evidence already exists. Do
not manufacture confirmation or clear a pause during deduplication.

Active uniqueness becomes `(tenant_id,condition_namespace,condition_key)` with
the current four-status predicate and nonempty-key behavior. Matching raw keys
from different old ledgers are not proof of duplicate conditions. Blank legacy
keys stay supported by exact row identity; new producers must supply a stable
nonempty episode key. Preserve current key semantics in slice 1.

For the approved prompt merger, reuse whitelist_suggestion as the internal
canonical type with display Software approval pending; avoid a gratuitous
public/internal rename. M5 gives active approval cases an episode_key derived
from tenant + product UUID + approval-decision dimension, independent of rarity
or affected membership. Convert active rare rows in place where unambiguous,
preserving UUID, legacy key, stored condition hash, pause and history. If both
old types represent one live case, manifest a survivor and close the other
as superseded with a replacement link; retain both histories. The reconciler
upserts by episode_key and uses the survivor's stored identity. Keep old
rare/non-approved switches as compatibility policy inputs until their effective
behavior has an approved mapping; do not silently enable a disabled population.
Type-wide exclusions, notification rules or divergent operator decisions require
explicit manifest treatment, not a blanket FK update to the broader type.

### Subject normalization and enforcement

Add `allowed_subject_kinds` to finding-type configuration, seeded from audited
producers and actual records, not blindly from old subject_scope. Core reference
validators are code-owned structural primitives; type-to-validator membership
is registry data. No arbitrary SQL/table names supplied through JSON.

| Current shape | Normalized subject |
| --- | --- |
| Existing client/device/software/installation UUID | Same subject/id, with tenant ownership checks for owned targets and existence checks for unscoped catalog targets. |
| Proposed PLAN-004 native source_record/source_record_case UUID | Validate the tenant-scoped durable source/case anchor and exact natural-reference/member agreement under PLAN-004's final design/ADR-0049. These are mechanism subjects, never fabricated canonical entities. Source association is optional context; independent evaluation starts at intake. Activation requires the reviewed coordinated common-store/domain artifact. |
| source_binding_id | Native binding UUID; validate binding/source instance tenant and optional client scope. |
| device_id in admin context | Computer UUID only when valid; do not infer from hostname. |
| source_binding_id + external_id | Source group reference including source instance/binding, namespace and exact external group identity. |
| topology source_id + external_ids | Explicit group-set scope; retain all group IDs rather than only the first old subject_ref entry. |
| Jobs signal_id/signal_kind | Validate against details and native schedule/run/dependency IDs or queue/job keys. Expose typed job_schedule/job_run/job_dependency/queue/job_definition/control-plane context. |
| Old platform-only, hostname-only or incomplete context | Retained legacy_context with original fields; no guessed UUID/client. Review/history remain available, unsafe actions disabled until the domain adapter establishes a valid target. |

Validate in the common DB mutation boundary/trigger, so ORM, raw SQL and bulk
producers cannot skip it. Migration alone may import validated legacy_context;
new runtime emitters must use a registered valid subject. Freeze the hashing
implementation in migration code; do not import mutable application code or
assume PostgreSQL JSON serialization equals Python's identity serialization.

## 4. Identity, assessments, history and actions

Add `finding_legacy_refs(tenant_id,legacy_kind,legacy_id,finding_id)` with unique
legacy reference and composite FK to findings. Original rows, including closed
ones, remain distinct. Old URLs resolve to retained history and any explicit
replacement link; they do not silently erase the old episode.

Keep legacy condition_participants/assessments keys and hashes, including
platform_signal participant IDs. Synthetic correlation IDs are not canonical
subjects; do not reinterpret them as binding/Job UUIDs. Common reads
join using `finding.condition_namespace`, never a hardcoded entity-only
predicate. The shared Condition adapter receives the persisted identity;
changing a display/type label cannot reset a prior judgment. Validate assessment
and participant ownership through a composite alias/identity FK or controlled
writer constraint; reject missing/cross-tenant references. No fabricated fresh
assessment is introduced during backfill.

Notifications retain condition keys, fallback fingerprints, cooldown state,
rule IDs and pending event references in slice 1. Resolve references through
the alias map. Semantic conversion manifests must specify old/new condition
identities and cooldown handling before type changes; pausing notification
workers is not permission to reset their state or send replay alerts.

History remains in existing change history. Legacy admin history keeps its
original table/key labels; the common reader combines lineage through aliases
and deduplicates by event identity. Backfill is recorded as a storage migration
action, not newly detected real-world incidents. Extend change_history_registry
for new fields/relationship tables and their intended capture classifications;
do not disable audit globally. Preserve original version values/references.

Keep source_action_requests IDs and exact source-instance/company/asset targets.
Recheck permission, handling, evidence and target immediately before a source
mutation. A broader UI group or issue replacement is not authority to retarget
a queued request. New bulk envelopes carry immutable scope, exact selected IDs
or an all-matching snapshot of exact item IDs; use Django's existing signing
support for a bounded compressed selection token, not a new queue/cache service.
Revalidate each current target, report changed/ineligible items and never
silently include later arrivals. Verify the same finding type
except eligible Pause/Resume. Publisher-wide effects remain explicit. Standard
confirmation and final outcome summary suffice; no extra preview subsystem.

## 5. One relationship mechanism and one state authority

Use a narrow domain junction because finding IDs already exist; do not turn
every finding into a new operations.entities anchor merely to reuse the generic
entity graph.

`finding_action_registry`: closed SQL key allowlist for UI actions and system
effects. It is the authority for relationship references; Operations
`FINDING_ACTIONS` supplies UI labels/permissions and validates its keys against
the allowlist at startup. Seed reviewed UI keys and system effects
(`condition.execute`, `notification.dispatch`, `notification.digest`,
`source.archive_hudu_asset`, and queue selection).

`finding_relationship_rules`: id, parent/child type IDs, kind covers/requires,
registered scope matcher, required match fields, notification suppression,
parent-satisfaction predicate, enabled/version/provenance.
`finding_relationship_rule_actions(rule_id, action_key)` references the closed
action registry with a composite primary key. No free-form names or implicit
“all actions” default. Requires must name at least one gated action. Covers
declares whether it suppresses each notification effect and any additional
action it blocks. Scope matchers are bounded structural operators (same
Computer/requirement, exact source binding, exact Job run/dependency or
validated source group), not arbitrary SQL expressions or undocumented
type-name branches.
PLAN-004 revision 8 adds no case-equivalence Covers matcher. It uses simple
one-key cases and audited duplicate references; shared members alone do not cover
independent work. Case combining is deferred to PLAN-033.

`finding_relationships`: tenant_id, parent_id, child_id, kind, rule_id,
scope/evidence fingerprint, validity/provenance and computed_at. Composite FKs
to both findings enforce same tenant; CHECK(parent_id<>child_id), kind enum and
unique current rule/endpoints prevent self/duplicate links. Preserve changes
and their reasons through registered history capture.

The SQL projector is sole relationship writer; runtime roles receive SELECT,
not direct relationship DML. PostgreSQL advisory locks are application-defined
and do not force writers to participate. Revoke direct runtime DML on all
graph-affecting inputs (findings, assessments, participants, type/rule
configuration, and relationships); route changes through granted
`SECURITY DEFINER` mutation functions owned by a dedicated no-login,
`NOBYPASSRLS` role that does not own the protected tables. Grant that role only
required table privileges; retain `FORCE ROW LEVEL SECURITY` and tenant
policies. Set function `search_path` to `pg_catalog, operations`, explicitly
check session tenant and caller contract version, and revoke EXECUTE from
PUBLIC. Each graph mutation function requires the tenant transaction advisory lock
in exclusive mode before finding, assessment, participant, rule or relationship row
locks, then mutates and projects in the same transaction. PLAN-004's shared tenant
mode for input-only transactions does not weaken this graph guard.
The caller selects its strongest mode at the outer transaction boundary; a nested
graph function verifies exclusive ownership and refuses a shared caller rather than
upgrading. Retry with the right mode from the outer boundary.
PLAN-004 adds no bucket/anchor lock plan. PLAN-003 owns and introduces the
migration-owned tenant-key helper with shared and exclusive modes; PLAN-004 reuses it.
Input-only protected entrypoints atomically advance one tenant input generation;
publication rechecks it under this exclusive guard after the input snapshot ends.

Database triggers only assert that the current transaction already owns
the expected lock by checking `pg_locks` for the backend and reserved advisory
key and exclusive mode; they never acquire it after row locks. Use the tenant-key helper's
fixed namespace and deterministic hashed tenant key, following the Jobs dependency
pattern. No PLAN-004 per-key lock namespaces are introduced.
Within a namespace a hash collision only adds conservative serialization; the same
tenant always maps to the same key. Apply exclusive mode to ORM handlers, ingest,
Jobs and notifications only when they mutate this protected findings graph or
PLAN-004's explicitly protected action/notification state; intake/association-only
ingest uses shared mode under PLAN-004's two write-set categories. Apply the same order to
source actions, bulk SQL, and migration/maintenance writers. Multi-tenant
operations acquire tenant locks in ascending order. The action registry and
mutation functions are migration-owned; grant only EXECUTE to required runtime
roles, not PUBLIC. Recursive reachability rejects cycles across both kinds
before publication.

The evaluator compares persisted input/version fingerprints first. An unchanged
assessment keeps the ADR-0031 touch semantics without a reachability rebuild;
protected writes still take the exclusive tenant guard. Changed graph inputs enter the mutation function before
assessment or participant row locks and project only the affected tenant/subgraph.
Bound synchronous traversal; exceeding the bound aborts with a retryable,
observable error. Rehearsal measures lock wait/hold time and affected rows under
concurrent evaluator/operator/rule changes, including timeout and retry behavior.
PLAN-004 revision 8 uses one assessment/publisher worker, bounded intake and
publication batches (including unchanged touches), configured statement/lock and
overall transaction timeouts, and durable retry accounting. No lock spans collection
or another network call. Its conservative tenant generation replaces per-key bucket
counters, not freshness validation: another record entering a candidate set must
invalidate an older result even if the target itself did not change. Indexed old/new
neighbor enqueue plus a coalesced paged refresh fallback must not lose dependent work.
Representative concurrency/load checks are required before deployment; no arbitrary
millisecond/100-outcome target or ticket coordinator is a release dependency.

New native source-record/case type keys are UI-only and non-alertable. Existing
legacy IDs/types/subjects/fingerprints, suppressions, cooldown and notification
producers remain unchanged. Do not introduce parallel findings for the exact same
legacy-owned correction or expand payload context. No source-specific dispatcher,
route-identity, reserve/send/record, alias, cutoff, sweep or catch-up redesign is in
this release. Common-store changes still retain PLAN-003's own coordinated artifact,
role/conservation checks and approval gates. PLAN-033/034 are separate deferred
plans, to be refined when activated; they do not block the smaller PLAN-004 scope.

### Live action guard

Relationships govern execution as well as queue display. Re-read finding state
and live links at request creation, worker claim, and immediately before final
delivery or mutation. Requires gates only the action registered by its rule;
viewing, evidence refresh, investigation, resolution, and repair of the
prerequisite remain available. Covers suppresses child selection/notification,
but preserves direct review and history. Covered children cannot start new
remediation or notification unless the rule explicitly exempts that action.
The action token includes relationship/rule version and evidence fingerprint.
Link, endpoint scope/evidence, rule, or endpoint-state changes invalidate
queued authority; stale workers cancel or re-evaluate. Existing permission,
evidence, freshness, and exact-target guards remain required. Acceptance cases
change a link after assessment and after queueing and verify request, worker,
and delivery rejection while review/handling remains available.

Existing finding/assessment/participant statement triggers call the projector
and refresh_finding_state in the same transaction. Extend trigger coverage to
all namespaces, changed subject/scope/evidence/handling, rule changes and
relationship changes. Cascade to affected descendants in bounded batches,
touching unchanged results as ADR-0031 requires. Bulk writes use transition
tables; no request-time full-fleet graph reconstruction or Python-only refresh.

Keep finding_state for derived technical assessment status and diagnostics;
add derived independent-work/relationship projections as necessary. Covered
eligibility must not disappear merely because a child assessment ages. Only
the projector determines live relation validity. Stale evidence does not
automatically prove either a cover or a recovery; domain rules must specify
what invalidates their causal evidence.

Covers hides only proven fallout. Requires leaves an independent row and gates
the relevant action. Pause, parent closure and filters do not constitute a fix;
parent changes re-evaluate links and child conditions. Root-most valid Covers
parents are displayed with chain detail retained. Independent higher-severity
risks must not be hidden merely because another problem exists. Retain the
previously required indication when covered evidence has higher severity than
its parent; related severity is impact context, not extra independent issue
counts or an invented Priority field.

### Initial rule conversion

| Rule family | Conversion contract |
| --- | --- |
| Offline/missing-source → agent reporting loss | Exact Computer/platform and reporting evidence must explain the loss. No blanket cover of confirmed missing installation. |
| Stalled patching → reboot pending | Remove automatic cover. Requires only with evidence reboot is a prerequisite. Offline does not erase the known reboot task. |
| Source failure → stale observations/assessment fallout | Exact binding/snapshot/client scope and causal evidence. A platform name alone is insufficient. Otherwise retain guard/context until association is proven. |
| Jobs failure → downstream wait | Exact prerequisite run or scoped incident evidence. Retain old closure history; prospective symptoms use the common graph. Expected within-window waiting remains Job state. |
| Unknown OS → unassessable requirements | No invented missing-installation assertion. Respect recognized OS and existing domain applicability. |
| Hudu-only → integration-gap task | No seed relation. Zero replacement of the verified 102 cases; a possible new feed is not their established cause. |
| Closed historical withdrawal/legacy types | No reopening by migration; retained reasons/history remain resolvable. |

## 6. Shared queue selection, metrics and URLs

Create a small Operations `issue_selection` module and SQL read adapter;
extract orchestration out of the large findings_queue view rather than add
another special result section. Rebuild v_issue_findings as one read-only
SELECT over findings with complete typed subject/client context and actual
last_detected_at fallback. Keep stable old columns/aliases for known consumers.

One normalized item relation combines finding rows with pending EntityCandidate
adapter rows, keyed by `(tenant,item_kind,item_id)`. Candidates keep their own
records/actions; do not fabricate Finding rows or repair PLAN-021 status in this
reader. Derive their display taxonomy/severity from the registered candidate
contract, not arbitrary critical defaults. Remove the auxiliary 200-row cap.

Selection order: tenant/access → allowed item population → lifecycle/pause/
valid cover → taxonomy and filters → table filters/search → counts/order →
selected page → hydrate only those rows. Unpaused independent Open is default.
Resolved history includes retained outcomes; direct covered detail is accessible
even when excluded from default counts. Use one request snapshot/normalized
scope for count/page queries; materialized values are read, not recomputed.

| Filter/metric | Meaning |
| --- | --- |
| Client | Direct subject client or explicit affected-client association. Product approval matching uses its uncovered installations; global issues are not treated as Unassigned. A filter never changes mutation/approval scope. |
| Severity/Status/Search | Same semantics across findings and eligible candidate adapter rows. Search only safe display/reference fields; no raw source payload search. |
| OS/Computer type | Exposed for Computer-specific work only; absent on software approval groups. Do not introduce OS-scoped approval semantics or show the withdrawn partial approval population. |
| Platform | Registered meaning for the selected work: source binding/platform for source work, requirement platform for agent work. Inapplicable item kinds do not silently bypass a constraint. |
| Group/header/Issues CSV counts | Count normalized independent issue items once over the full selected scope. Open and Paused are disjoint; related covered items are not independent work counts. |
| Affected Computers | Distinct impact, separate from issue totals. Approval rows describe the full uncovered population of that decision case; disclose global decision scope. Scoped Computer export is the distinct matching exposure population, not an issue-row export. |

Specify client-filtered approval output carefully: Client selects cases affecting
that client, while the approval case retains its complete uncovered population.
Global approval confirmation remains explicitly global; do not silently turn
filter scope into a policy scope. Issue totals and impact totals are different
units and must not be compared as if they were the same count.

Keep existing /issues and review routes. Canonicalize view, taxonomy, severity,
status, filters, sort and group-page state once and reuse them in all links.
Opening a sibling preserves/restores its sort/page but clears action selection.
All-selected subgroup means that subgroup across pages, never its parent.
Reject invalid selection/type/tenant references server-side. An invalid or
retired scope cannot silently broaden to all work; show an explanatory empty
scope or an explicit supported redirect. Legacy removed Attention filters get
an explicit migration notice rather than inventing an equivalent readiness.

Render selected rows beneath their active header, not after all unrelated
sections. Server-rendered links/fragments suffice; no new frontend dependency
or universal workspace. Review links target existing domain context with a
validated return URL. Home mapping count and destination use the exact same
selection helper and include all relevant Critical mapping types.

## 7. Proposed migration sequence and data effects

Numbers below reserve the next slots after observed 0353; rebase/renumber if
another approved migration lands. No migration files have been created or run.
Only schema expansion may run with old writers; cutover/backfill requires the
explicit coordinated window and the new writer/reader bundle.

| Planned migration | Exact intended operations and guard |
| --- | --- |
| M1 / next available migration slot at implementation | Expand schema and add constraints/adapter scaffolding only. Do not reserve a numeric filename in design: 0354 is occupied in this worktree. Package only M1 and backward-compatible model state; old readers/writers remain valid. |
| M2 / assigned after rebase | In the coordinated cutover artifact, under writer quiescence, preflight UUID/key/subject/assessment consistency; populate metadata; copy every admin row with exact field map and aliases; preserve history and migration audit. Do not serve or admit workers between M2 and M4. Exact-set reconciliation must pass. |
| M3 / assigned after rebase | In the same artifact and uninterrupted maintenance window, install namespace-aware state functions, trigger lock assertions, controlled mutation procedures, projector and graph constraints. No process is admitted against this intermediate schema. |
| M4 / assigned after rebase | In the same artifact, atomically cut over views, indexes, models and writer/reader code. Retain admin_findings as read-only projection over admin-namespace rows. Keep page assembly on two namespace-filtered readers until slice 2. Assert exact identity sets for both paths, home counts and domain counters against baseline, plus disjointness and union conservation. Publish contract version 4 only after assertions; all Operations, ingest, Jobs, notifier and source-action processes require version 4 at startup and each write/action boundary. |
| M5 / separately approved semantic release | Ship only reviewed per-type manifests and behavior; require contract version 5. Preserve episode/history mapping, notification continuity and reasons. Apply approved removal of Readiness presentation and set device_unenrolled alertability false for its inventory/lifecycle-review meaning. ADR-0043 waits for PLAN-004 measurements. |
| M6 / later separately approved release | After rollback window and zero-access evidence, retire legacy active interfaces while protecting retained history/aliases; require contract version 6. Package migration and code together. Do not drop historical rows as routine cleanup. Re-audit SQL/roles/clients. |

M1 may be released as a backward-compatible expansion artifact after schema
review. M2, M3 and M4 migrations and matching code ship together in one
coordinated release artifact, applied during a single drained maintenance
window; startup must not admit Operations or workers until M4 commits version 4.
Operations applies every pending migration, so M5/M6 files must not ship with
M1 or the M2–M4 artifact. M5 and M6 each require separate release artifacts and
approval; M4 approval does not authorize them. Assign migration dependencies
only after rebasing on the then-current graph. M2–M4 must not be applied
automatically to running old producers. Existing Operations entrypoint applies
migrations at startup and Compose updates services independently; a push alone
does not provide quiescence. Final deployment must have a reviewed maintenance
gate that stops new admission and drains/fences all finding producers, notifiers
and source-action workers before M2. Keep operator writes/read maintenance safe.
Back up/restore-test before the window. Do not improvise stopping services as
part of this design task.

Required deployment sequence: stop operator writes by stopping the old
Operations service; stop new ingest admission; gracefully drain/stop old ingest
and Jobs worker containers (respect the existing worker 120-second grace).
Verify no old producer/notifier/source-action transaction remains before the
approved release update. Operations entrypoint runs M2–M4 with migration-role
credentials supplied by its existing private environment, then switches to
the runtime role before serving. Do not copy those credentials into a manual
command or this package.

Publish a monotonic read-only `operations.finding_contract_version()` as the
last transaction operation of each deployable artifact that changes a contract
(M4, M5, M6; M1 only if its contract changes). Every process declares its
supported contract-version range in the immutable application artifact and
checks at startup. Read-only processes may
use a range only where compatibility is explicit. Any process that writes or
performs a guarded action must require the exact contract generation it was
built for, checked both at startup and at the database mutation/action boundary;
database procedures reject a stale compiled caller version. This detects stale
known binaries; it is not process attestation. The drained release procedure
remains mandatory because a runtime role can issue arbitrary SQL and claim a
version. A contract upgrade therefore fails closed for old processes on
restart, while live old processes must be drained before migration. M4 publishes 4 only after exact
population and permission assertions. M5/M6 publish 5/6 only in their separate
artifacts. Grant EXECUTE only to required runtime roles, not PUBLIC. Review
Operations, ingest, Jobs, notifier and source-action entrypoints together. The
version gate supplements, but never replaces, draining old processes.
Abort on an ungraceful drain, unknown
old writer or contract mismatch rather than proceeding with mixed writers.

### Reconciliation and abort conditions

- Preflight current all-tenant scope through an authorized role; the tenant-1
  zero-collision result is not certification of every tenant. Inventory all
  configured consumers, including external Metabase/saved SQL not in Git.
- For each legacy row compare id, version, tenant, type, key, subject evidence,
  status, severity, times, pause/decisions, details and references against its
  mapped row. Compare exact populations/hashes, not only totals. Account for
  every semantic change in M5 separately from mechanical M2 conversion.
- Verify assessments/participants/condition hashes, notification state/events,
  source-action targets, history lookup, RLS and candidate independence. Abort
  on any unexplained missing/duplicate/changed population or unauthorized role.
- Record timings, locks, WAL/storage growth and rollback evidence on an
  authorized isolated rehearsal. No downtime duration or performance result
  is claimed yet. Set operational bounds from rehearsal, not guesses.

### Rollback boundaries

Before M2 commit, transaction rollback preserves both old ledgers. Before new
writers resume, verified reverse migration can restore old functions/views/
indexes and remove only mapped imported rows while retaining audit evidence.
Once new unified writes occur, old admin_findings is stale: rollback requires a
tested reverse export of new/changed admin-origin rows, updated pauses/subjects,
assessments and references, or a forward repair. New typed subjects/semantics
may not fit the old schema. Do not promise old-code rollback past that boundary.
Take the second recovery checkpoint before M5 semantic conversions; never
undo operator decisions by restoring an old database snapshot over live writes.

## 8. Validation and review gates

Required implementation tests: real PostgreSQL with production role attributes;
all namespace/status/subject variants; metadata identity round-trip; same-tenant
FKs and negative cross-tenant cases; concurrent cycle rejection; rule/evidence
and pause/closure cascades; expired child assessment with valid cover; no
historical Job-child reopening; source action freshness/target recheck; stable
notifications/cooldowns; and no broadening/partial action without reporting.

Queue fixtures must include >500 rows, several pages and all item kinds,
multiple groups/severities, paused/resolved/covered and missing metadata.
Assert header/results/Issues CSV identity sets, distinct Computer export,
independent group sorting/paging, candidate count conservation, same-type bulk
gates, mixed Pause/Resume and action scope under filters. Browser checks cover
home Critical mapping jump, default highest-priority path, one sibling, return
state, mobile and empty/error cases. Measure landing ≤1 s/filtered ≤3 s on the
agreed environment; demonstrate plans/index usage before claiming performance.

Final package needs explicit review of:

1. Approved Readiness removal and resulting presentation/order, listed in the
   current design.
2. Approved alertability exception in the ledger: unenrolled inventory review
   is not a protection-gap alert. M5 changes its true flag to false; storage-only
   conversion preserves all 21 flags until that semantic change.
3. Exact code/migrations, all-tenant reconciliation and rehearsal evidence,
   maintenance procedure, measured bounds and rollback compatibility. These
   require implementation/rehearsal authorization before execution or release.

Design validation is limited to reference coverage, document links, registry,
governance and whitespace. Runtime tests, migration execution, browser results,
external-card audit and recovery rehearsal have not run for this docs-only
package. VERSION/CHANGELOG stay unchanged. Existing documentation debt is
docs/current-state.md older than 90 days.
