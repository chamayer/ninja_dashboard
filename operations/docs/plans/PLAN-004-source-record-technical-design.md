# PLAN-004 — Source-record implementation design

Status: Supporting integration inventory, 2026-10-29. The
[final design](PLAN-004-source-record-final-design.md) is the controlling proposal
and resolves earlier model, type, policy-default and rollout alternatives below.
Revision 8 narrows the release to simple cases and silent native types; older
lock, policy, conversion and notification proposals below are historical inventory,
not requirements. PLAN-033/034 are deferred placeholders to refine on activation.
This inventory connects it to the
[domain design](PLAN-004-source-record-design.md) and
[rule/action contracts](PLAN-004-source-record-rule-contracts.md).
No runtime files, migrations or source data have been changed. Discovery stopped
at user request. Local integration reads inform packaging, not the requirements.

## Proposed first-policy behavior

| Decision | Proposed policy |
| --- | --- |
| Managed admission and applicability | Every record enters managed/evaluable Operations scope immediately. Schedule applicable non-identity evaluations without resolver completion. Missing role/context limits the particular rule and remains explicit; it never makes the item globally ineligible for evaluation |
| Discovery | Union usable identifiers, normalized/current/former names, usable MACs and typed references within authorized comparable evidence. Domain/group and timing qualify/explain candidates; they do not produce every possible pair |
| Weak evidence | Preserve same-name and MAC-only candidates, including differing-name MAC matches. Show independent supporting/opposing signals and relay lineage. No additive confidence score or weak-match transitive identity |
| Name-based association | Justify scope, normalization, specificity, uniqueness and conflicts for each automatic rule; do not grandfather the current rules. Missing serial does not exclude name evidence. Weak discovery outside automatic-action scope remains available |
| Supported hardware association with unknown source group | Unknown attribution is different from contradictory attribution. A unique corroborated tenant-local match may qualify under ADR-0048 after identity/exclusion/ownership guards. Preserve the source group as unmapped; association cannot confirm its ownership or map the group |
| Contradictory ownership or identity | Present the specific conflict. Refuse automatic mutation; current association is evidence to challenge rather than an override of contrary claims |
| Purpose | Required/permitted/excepted/disallowed are explicit authored policy. An active real installation may still be unwanted; an optional service is not automatically unwanted. Unknown purpose does not automatically authorize cleanup |
| Replacement | Require supported same object/role plus trustworthy supersession or adequate succession chronology and no contrary continuing purpose. The measured ScreenConnect pairs do not satisfy this proof |
| Stale age | No numeric default. Evaluate only an approved source-role/time/threshold policy with its exceptions and adequate collection; otherwise unknown. Proven replacement has no additional age wait |
| Source actions | No new automatic deletion, archiving, software removal or collection is enabled by assessment. Each exact operation remains permissioned, explicitly requested and guarded |

These are proposed defaults for approval, not statements that all enforcement
already exists. The domain design's justification table proposes changes to
ADR-0032's Computer-association wording and recency-based ambiguous selection.
Universal managed admission is justified by the user's evaluation requirement;
final Computer identity cannot be its prerequisite. Its
name-based action rules also require justification. None is silently retained or
changed merely because of previous approval; actual policy changes need an explicit
reviewed amendment. Keep useful name evidence without requiring every asset or
documentation record to have a Computer.

## Logical data additions and ownership

Physical migration names/numbers are assigned only against the current migration
graph at implementation. The following is the proposed schema contract, not DDL.
Source references use PLAN-003's versioned structured-subject validator.

| Store/contract | Required fields and constraints | Writer and purpose |
| --- | --- | --- |
| Record assessment current | Tenant; stable source tuple/reference; rule key; claim/decision dimension; policy digest; input fingerprint/generation; result and explanation; evidence references; measured/valid-until times. Unique tenant/source/rule/dimension. Reject cross-tenant references and unknown rule versions | Assessment projector only; permits supported/unknown/no-issue results without fabricating a finding |
| Comparison evidence | Stable endpoint references, discovery reasons, independent evidence lineage, contrary/missing signals, rule/policy/input versions. Unordered pair identity is canonicalized; no asserted equivalence from membership | Comparison projector; bounded and rebuildable. No operator state belongs in this output |
| Input invalidation | Stable source target, monotonically ordered decision-relevant generation, dirty reason and work scope. Include status/contact changes even when material hashing intentionally excludes them | Observation/decision/policy mutation boundary enqueues registered work; no arbitrary background table polling as correctness mechanism |
| Current eligibility read | Per source/claim/intended-use answer, reason, policy/input generation and validity. Missing/stale results remain unknown; do not equate a finding's status with claim validity | Assessment/eligibility read adapter, used by every converted consumer |
| Operator decisions | Exact concern/target/evidence scope, action, actor, reason, decision version and expiry/change trigger. Preserve existing identity/mapping decisions through validated adapters | Existing guarded action boundary extended for approved domains; never overwritten by a source refresh |
| Issue targets/members | Common finding UUID/episode identity; source-record structured target or set; exact members; optional validated Computer/client context; retained alias/supersession mapping | PLAN-003 protected finding/subject writer; no third finding ledger or synthetic canonical entities |

No raw customer payloads are copied into assessment results or general-purpose UI
JSON. Reference evidence and expose safe selected fields. Persist changed assessments
and case decisions as auditable history through the reviewed history mechanism;
do not write one history row on every unchanged heartbeat. Raw source/observation
history remains authoritative for original assertions.

Forced tenant RLS and composite tenant/reference checks apply to new scoped stores.
Runtime app reads safe views and executes allowlisted guarded actions; it receives
no general DML on derived assessments or source observations. Ingest receives only
the privileges needed for its evidence and projector functions. New read views
explicitly revoke runtime DML. History access must enforce current record restrictions.

## Correction propagation and generation checks

Managed admission and independent non-identity evaluation form a direct path
from source evidence. Identity resolution is a separate consumer; it must not
be a prerequisite Job/dependency for all record assessments. Context-dependent
evaluations rerun when identity/ownership information becomes available.

1. Commit the original source evidence or operator decision with an input-generation
   change and registered dirty work in the same transaction. Source identity keys
   remain stable when names, mapping or attachment change.
2. Recompute affected record-level checks and comparison neighbors using a consistent
   evidence generation. Changed mapping/association invalidates dependent context,
   not the original source assertion. Policy changes invalidate their declared scope.
3. Publish assessment/eligibility results only if the consumed generations still
   match. A newer input prevents an older worker from publishing a fresh verdict.
   A failed or batch-limited run leaves explicit outstanding work and cannot claim
   assessment completion or clear issues.
4. Dirty the affected authoritative projection/identity/requirement consumers.
   Consumers may use independent unaffected evidence; an unassessed changed claim
   cannot establish a new automatic decision. Retained last-known state is labeled
   separately from a fresh supported result. Do not turn unknown into absence.
5. Publish projected current state before completing its dependent evaluation and
   selection/count update. Reassess closure only against the required completed
   generations. Retry idempotently; a newer generation supersedes an older result.

The ordering above applies only to each actual data dependency. Record rules that
need no identity-derived projection complete directly from source evidence and
their own assessment generation, even while identity or a Computer projection fails.
Do not use one all-or-nothing pipeline completion flag for every kind of evaluation.

Read/review remains available while projection is pending. Action previews include
target, policy, evidence and operator-decision versions and expiry; execution rereads
under the protected mutation boundary and refuses stale preconditions. Lock order,
tenant serialization and exact contract generation follow PLAN-003. No read request
starts a hidden source collection or writes derived state.

Accuracy and claim eligibility must not depend on a downstream effective value
selected from that same claim. Identity/mapping context may refine later checks,
but dependency cycles are rejected. Time-triggered stale/expiry work is scheduled
explicitly, because a threshold can cross without material evidence changes.

Important local integration fact: `ingest/derived.py` currently labels attribute
claim/effective projections as shadow paths and continues after their failure.
This plan does not promote those paths by implication. Preserve each current
authority until a reviewed consumer manifest selects and validates its replacement.
Coordinate any broader authority promotion with the owning architecture plan.
Only a newly authoritative mandatory dependency becomes a completion gate; unrelated
shadow failures must not accidentally block collection or all source-record review.

## Proposed affected components

Paths below are an implementation inventory, not authorization to edit runtime.

| Area | Proposed files | Intended change |
| --- | --- | --- |
| Pure rule and reference contracts | New `shared/source_records/contracts.py`, `policy.py`, `assessment.py` | Typed source references, comparable roles/claims, lineage, rule outputs, versioned policy validation; no connector credentials or Django models |
| Managed admission and invalidation | `ingest/observations.py`, `ingest/source_observations.py`, `ingest/connectors/screenconnect.py` and source adapters with pre-write filtering | Admit addressable records before identity/name filtering; account for malformed/excluded inputs. Enqueue decision-relevant changes including volatile activity/status; retain raw evidence and source semantics |
| Assessment/comparison orchestration | New `ingest/source_record_assessments.py`; `ingest/derived.py`, `ingest/main.py`, `ingest/operator_job_queue.py` | Bounded dirty-target work, consistent generations, source-role adapters and scheduled age evaluation; register existing Jobs/queue contracts |
| Identity/attribution | `ingest/identity/matching.py`, `resolver.py`, `findings.py`, `client_resolver.py` | Reuse evidence results, include unassigned comparison evidence, retain name policies/exclusions, separate original group attribution |
| Findings and maintenance | `ingest/evaluator.py`, `ingest/cmdb_findings.py`, `ingest/conditions.py`, `ingest/condition_evidence.py` | Qualified record-target findings, complete assessment/closure evidence and overlap conversion |
| Claim consumers | `ingest/attribute_claims.py`, `effective_attributes.py`, `device_cache_projector.py`, SQL projection functions, requirement/lifecycle readers | Apply use-specific eligibility only at the reviewed authority cutover; audit source readers and preserve the sole projector writer |
| Safe UI read adapter | New `operations/apps/core/db/source_records.py`; safe metadata-view migrations | Tenant/restriction-safe record and comparison details with absent Computer/client support |
| Resolution and selection | `operations/apps/core/views.py`, `identity_actions.py`, `conditions/`; `operations/config/urls.py`; `templates/source_records.html` and proposed source-record review template | Comparison workspace, explained recommendations, guarded actions, shared Issues/count/export contracts; retain old deep-link compatibility |
| Source execution | `ingest/source_actions.py` and Operations action entrypoints | Revalidate exact target/policy/input generation; permit only explicitly approved supported operations; source link/manual repair remains available otherwise |
| Database/models | `operations/apps/core/models.py`, new Django migration modules and relevant SQL function changes | Assessment/queue references, structured subjects, constraints, RLS/grants, function ownership and validated writers; allocate exact migration order after rebase |
| Validation | New focused shared/ingest rule tests; PostgreSQL generation/RLS/episode tests; Operations review/request/export/action tests | Verify the acceptance matrix below, without synthetic customer identifiers or production payloads |

Detailed rule adapters are source-record-role contracts. Add connector changes only
when a declared evidence field actually requires them; do not change every connector
merely to add the shared assessment capability. Same for Computer requirements:
audit their evidence use without expanding their applicability universe.

Both Dockerfiles copy `shared/` and their complete application directories, so
the proposed files fit existing image copy paths. Recheck packaging after actual
file additions. No new dependency, service, public port or Compose service is
proposed. No secrets or environment changes are required by this design.

## Migration, conversion and rollout

| Stage | Proposed operations | Required exit evidence |
| --- | --- | --- |
| Expand | Add versioned rule/reference/assessment/queue schema and safe reads without changing live identity, findings or selected values | Migration/model agreement, runtime-role denial/grant tests, old consumer compatibility |
| Assessment-only validation | Run against test-created local evidence and compare expected outcomes; any production measurement needs renewed authorization | Every declared role reports supported/unknown/not-assessed accurately; no hidden source calls or action effects |
| Common-store cutover | Integrate source-target validation with PLAN-003 M2–M4 as one drained artifact; preserve IDs, operator state, aliases and exact assessment identities | Exact-set conservation and role/concurrency checks; no worker admitted between incompatible generations |
| Domain semantic conversion | A separately approved package activates record-level detection/workspaces and reviewed consumer eligibility together with explicit per-family manifests | New/unassigned cases included, intended legacy rows retained/converted/closed with reason, no duplicate work or new notification storm |
| Operational acceptance | Separately approved release/deployment validation, then any specifically approved evaluation/backfill | Deployed artifact and migrations, anonymous outcome/count reconciliation, UI/action/closure checks |

Do not ship future pending semantic migrations with an earlier artifact: startup
automatically applies them. PLAN-003 M5 semantics are separately approved from
mechanical storage conversion. PLAN-004 completion requires its agreed full behavior;
an assessment-only or UI-only slice is explicitly incomplete.

Each legacy finding family needs a frozen conversion manifest: original UUID and
namespace/key, validated source/action target, successor identity or retain outcome,
assessment/participant mapping, operator state/history, and closure reason if changed.
Platform/name-only legacy context remains inspectable with unsafe actions disabled;
it is never assigned a guessed source ID, client or Computer. Duplicate platform,
unlinked identity, mapping, placeholder and Hudu families are audited separately.
Preserve independent requirement/security findings unless exact causal resolution
is proven. No broad close-and-regenerate operation is proposed.

Rollback is artifact/schema-generation specific. Stop new actions and incompatible
writers first; retain observations, decisions and issue/history identities. Before
semantic cutover, disabling the additive path restores prior authority. After
conversion, use the reviewed checkpoint/reverse mapping and compatible writers;
do not blindly reverse copied rows or restore stale evidence eligibility. Production
rollback, restore, backfill, source mutation, commit and push remain separate approvals.

## Acceptance package and remaining policy choices

Test-created representative cases must prove:

- A single inaccurate or unjustified record is assessable without attachment.
- Every source record has a managed evaluation target before resolver completion;
  stalled/failed identity cannot prevent independent non-identity findings/actions.
- Name-only, normalized/former-name and MAC-only comparisons retain value; repeated
  or relayed name evidence does not inflate confidence; weak links are nontransitive.
- Different same-name machines, clones/roaming and source-instance ID collisions
  do not cause false association/cleanup; a legitimate multi-record purpose survives.
- Unknown group versus contrary client evidence stays distinct; restricted records
  cannot leak through candidate lists, counts, errors, recommendations or exports.
- Connected plus unknown activity remains representable; qualified replacement has
  no age gate; missing policy/time and partial snapshots cannot prove staleness/repair.
- Invalid serial exclusion does not erase valid connectivity or a real unwanted
  installation; purpose/handling state cannot bypass claim validity.
- A correction invalidates affected inputs, old workers cannot publish over new
  generations, retries preserve episodes, and interrupted projection cannot clear work.
- Preview/execute races refuse stale actions; exceptions reopen on relevant changes;
  withdrawal/reappearance and membership changes preserve history and exact scope.
- HTML/CSV, global/client/Computer drill-through and shared Issues count the same
  corrective work once, with independent corrections still independent.
- Migration conservation, RLS/grants, protected writes, query plans and bounded
  generic-name fanout meet the reviewed runtime-role/performance contract.

Run targeted Python/shared tests, PostgreSQL integration tests, Django checks,
template/request/action smoke tests, relevant Ruff checks, registry validation,
packaging review and whitespace checks in the documented isolated environment.
Record actual outcomes and unavailable checks; no runtime tests were run for this
design-only document.

The final design selects native source-record/case subjects, assessment dependencies,
the first automatic-action policy, condition/severity mappings and explicit unknown
behavior for missing deployment policy. ADR-0049 records the proposed amendments.
Executable DDL/function bodies, migration filenames and measured runtime performance
are implementation-stage deliverables, not facts established by this design inventory.
