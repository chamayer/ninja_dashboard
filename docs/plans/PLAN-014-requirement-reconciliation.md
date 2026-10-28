# PLAN-014 — Requirement and lifecycle reconciliation design

Status: baseline deployed as `0af8aac` (release 0.129.3); acceptance resumed at
the user's request to finish PLAN-014. The explicit-confirmed-use policy was
accepted on 2026-10-27. Current diagnosis and validation are in the
[acceptance record](../records/PLAN-014-acceptance-2026-10-27.md). The user approved
preparing the reported-state fallback for the remaining contactless Computers;
the candidate and migration 0357 are locally validated, not deployed. Earlier
test results do not establish production acceptance of this candidate.
Deployment provenance: [build checkpoint](../records/PLAN-014-build-2026-10-27.md).

Registry: [PLAN-014](../records/PLAN_REGISTRY.md). Active handoff:
[`ingest/BLUEPRINT.md`](../../ingest/BLUEPRINT.md). Prior local evidence:
[validation record](../records/PLAN-014-validation-2026-10-27.md).
Policy amendment: [ADR-0047](../../operations/docs/decisions/0047-requirement-lifecycle-reconciliation.md).

## Goal and boundaries

Make a Computer's lifecycle decision, effective requirements, stored verdicts,
findings and recovery agree, while preserving evidence, operator decisions
and historical episodes. Correct the diagnosed drift through normal evaluation,
not a blanket cleanup or a new competing source of truth.

PLAN-014 owns this domain repair. PLAN-012 retains inventory populations and
other page readers. PLAN-004/015/021 retain identity and candidate lifecycle.
PLAN-003 retains the shared findings ledger and typed relationship redesign.
This work precedes PLAN-003 in the overlapping evaluator paths. It must not
introduce a second relationship engine or declare PLAN-003's proposed changes
to existing cover semantics implemented.

## Accepted policy: explicit confirmation of use

An existing, valid tenant-scoped `in_use_confirmed=true` operator decision
restores the Computer to the requirement universe and bypasses the
`pending_cleanup` requirement exclusion. It does not assert online status,
change lifecycle to active, invent agent evidence or bypass OS applicability,
exemptions, source/identity guards, clearing checks or operator handling.

Normal requirements apply only after this exception is considered. A known,
supported OS can produce a missing requirement even without agent records.
Unknown OS still prevents OS-limited requirements and produces the existing
unknown-OS condition; explicitly Unknown-compatible requirements remain
eligible. An explicit disabled client requirement remains disabled.

Removing the confirmation restores ordinary applicability on the next run.
Reporting again follows the existing audited confirmation-clearing behavior.
A confirmation alone does not restore a retired or deleted Computer; existing
retirement/restore rules retain authority. The exception applies to valid
cleanup Computers, not all historical subjects.

This specifically amends ADR-0036's unconditional cleanup exclusion and
reconciles it with ADR-0032. It is an operator decision, not the rejected
automatic "alive elsewhere" exception.

## Accepted continuation: contactless explicit-state fallback

The user approved preparing this change on 2026-10-27 after the read-only
diagnosis identified 45 review entries on 20 Computers. Add the registered
`direct_contact_state_fallback` mode for `agent.remote_access` and
`agent.monitoring`, keeping the single `entity_types` capability authority.
Use it only when no source supplies qualified direct contact for the Computer.
Existing modes, including the hybrid VM-host mode, retain their selection rules.

Recognized positive state can support recovery. A negative fallback establishes
current offline state with unknown duration: it cannot infer old contact,
contact-aging cleanup or a new extended-offline finding, and it preserves an
existing offline episode until recovery is positively established. Requirement
assessments use `offline:reported_without_duration` rather than asserting
extended absence. Source-health, identity, operator, OS and retirement guards
remain enforced. Missing, null, unknown and conflicting state remain uncertain.

Migration 0357 extends the existing constraint and Django choices, changes only
the two reviewed type registrations under an audited change action, and refuses
unexpected starting policy. It does not rewrite observations, verdicts or
finding history. Its reverse restores contact-only registration/constraint;
rollback does not undo lifecycle transitions or their audit history. Release,
production migration, recalculation and rollback require separate approval.

## One shared lifecycle evaluation result

Produce one transient result per selected Computer from a consistent input
snapshot. The result is not a new persisted lifecycle table or a UI-derived
calculation. Reuse the registered evidence modes, source-listing classification,
evidence selection and tenant/client thresholds already owned by lifecycle.
The lifecycle writer consumes this result and remains the existing writer.

Each result carries:

- Tenant/Computer identity, evaluation time and selection scope.
- Proposed lifecycle and the precise reason: qualified contact policy,
  documentation-only, stopped-VM, archived/nothing-listed cleanup,
  confirmed-in-use, retirement, or unmeasured/conflicting evidence.
- Selected evidence kind, source reference, evidence time and qualified last
  positive contact when known. Collection/observation time is separate.
- Applied thresholds, relevant source completeness and conflict/unknown state.
- Distinct decisions for coverage exclusion, offline-condition eligibility,
  cleanup-condition eligibility and whether recovery can be assessed.

Missing/conflicting evidence does not turn the old stored lifecycle label
into a newly proven fact. Preserve the label/history when policy requires it,
but consumers receive the uncertainty and cannot use it to grant clearing.

### Time and offline semantics

A collection timestamp is never substituted for positive device contact.
A current, explicitly reported online/offline state remains qualified evidence
under its registered mode; it is different from a successful fetch of a record
with no reported state. A documentation poll cannot establish liveness.

Keep current tenant/client thresholds and exact boundary behavior. Distinguish
"reported offline now" from "offline beyond the configured threshold." A new
extended-offline assertion needs qualified duration evidence; a fresh negative
report with unknown duration cannot invent an old last-contact timestamp.
Where duration is unmeasured, retain uncertainty rather than forcing an
offline parent merely to eliminate drift. Existing lifecycle evidence selection
and conflict rules must remain explicit in the implementation.

### Consumer mapping

| Shared result | Requirements | Root condition |
| --- | --- | --- |
| Active, qualified reporting/contact | Evaluate eligible requirements | No offline/cleanup condition from that evidence |
| Qualified contact aging before cleanup | Evaluate eligible requirements | Offline when its threshold is established |
| Contact-aging cleanup, no explicit confirmation | Record non-applicability | Offline when qualified evidence establishes it |
| Documentation-only, stopped VM, archived or nothing-listed cleanup | Record non-applicability | Existing precise cleanup reason, not a fabricated offline condition |
| Valid explicit confirmed use in cleanup | Evaluate eligible requirements | Existing confirmed-use handling; no fabricated online/offline assertion |
| Unknown OS within the eligible requirement universe | Apply only explicitly compatible requirements | Unknown-OS condition where applicable |
| Retired/deleted | Exclude from current requirements | Preserve history under existing retirement policy |
| Incomplete or conflicting evidence | Record only supportable conclusions and guarded uncertainty | Existing exact source/conflict condition; no invented absence or clearing authority |

Offline producers, requirement offline guards and cleanup producers consume
this same result. They do not re-read `lifecycle_status` as a complete answer
or independently compare contact/collection timestamps.

## Requirement decisions and episode reconciliation

The coverage pass resolves profile inheritance, role scope, sparse client
overrides, explicit confirmation, exemptions, OS compatibility and qualifying
presence once. It produces the stored verdict and desired condition together.
Full logical identity is tenant, Computer, entity type and platform; desired
episode identity also includes finding type and the existing condition key.
Wildcard presence is resolved by the same coverage calculation.

Every selected active old episode is reconciled against this result, including
satisfied requirements, removed profiles, changed clients/keys, unsupported OS,
explicit exemptions and missing/stale transitions. Conditions that disappeared
receive newly measured assessments too. Never borrow an assessment from another
episode, tenant, entity type, policy version or earlier incomplete pass.

Keep matching episodes and their operator handling. Create a new episode only
under the existing episode contract. Obsolete episodes close only with current,
complete, correctly scoped clearing authority. Unknown-OS/cleanup findings that
policy intentionally retains preserve their history and the actual covering
condition. Missing evidence of an appropriate parent remains diagnosable;
do not create a generic offline parent to satisfy the checker.

Explicit confirmed use restores checking, not permission to notify/execute or
clear through an offline/source/identity/suppression guard. Existing cover
behavior remains visible. PLAN-003's independent-missing-installation and
typed-relationship changes stay coordinated work, not an implicit semantic
change hidden in this repair.

## Transaction, ordering and scope

Use the same scoped pipeline for a full tenant pass and a single Computer:

1. Establish tenant context, evaluation serialization and a consistent input
   snapshot before loading configuration, source health and lifecycle evidence.
2. Compute shared lifecycle results and apply their existing audited transitions.
3. Compute requirement verdicts and desired conditions from those results.
4. Reconcile root and requirement episodes with current assessments. Root
   opening/closing and existing live cover settle in the same transaction.
5. Publish verdicts and commit the coherent result, then run the read/audit
   check through its existing separate recording transaction.

Implemented mechanism: serialize overlapping evaluations per tenant with a
session advisory lock and use a repeatable-read input snapshot.
Acquire the evaluation lock before any finding/assessment row locks and before
establishing the evaluation snapshot; the concrete connection/transaction
sequence acquires a session advisory lock in a short acquisition transaction,
then starts the repeatable-read transaction and releases the lock in a final
transaction, including on failure. A serialization failure rolls back the
whole pass and is reported; it must not publish partial verdicts or silently
replay operator actions. Configuration/source changes committed afterward
belong to a later evaluation. Admission/retry behavior needs explicit review
against existing Jobs behavior during deferred validation; no new automatic
retry or operator-action replay was introduced.

The transient result is complete only for its declared scope. A single-Computer
pass cannot replace another Computer's verdicts or reconcile its findings.
No update may cross tenant boundaries. No new runtime dependencies, public
API or persisted authority is proposed.

## Audit and compatibility

Retain raw disagreements and their first/last detection history. Separately
explain deliberately retained episodes using the exact current policy,
assessment, guard or applicable cover relation. An old/missing assessment,
missing expected root, or merely matching platform name is not an explanation.
Do not classify all blocked or covered rows as correct by default.

Completion means zero unexplained contradictions, not deletion or suppression
of all raw audit rows. Root/finding/verdict reconciliation must use full tenant,
Computer, entity-type and platform identity. Review the existing 0333 SQL
checker, which joins verdicts using Computer/platform without entity type,
before relying on its counts as exact acceptance evidence. If correction
requires a migration, prepare a new reviewed forward migration; never rewrite
0332/0333 or run production DDL without approval.

Preserve stored verdict vocabulary and reader compatibility unless review
demonstrates a necessary change. Human-facing labels must distinguish cleanup
from a proven offline condition and show confirmed-use requirements from the
stored verdicts. Inventory populations and unrelated page calculations remain
outside this plan.

## Affected files and implementation sequence

- `ingest/evaluator.py`: shared result, writer/consumer wiring, exact episode
  reconciliation, full/single scope and recovery ordering.
- `ingest/computer_listing.py`: reuse existing listing reasons; clarify the
  accepted confirmed-use behavior without a second lifecycle algorithm.
- `ingest/requirement_state.py` and the existing check/report surfaces: exact
  audit interpretation; inspect callers before changing any contract.
- Relevant Operations verdict labels/templates and focused tests only where
  the new distinction needs to be rendered; inspect existing readers first.
- A new Operations migration only if the reviewed checker/compatibility repair
  needs one. Existing migrations remain unchanged.
- ADR-0047, ADR-0036 amendment, this design, registry and ingest blueprint.

First implement the shared result and confirmed-use precedence, then wire all
domain consumers and scoped recovery. Integrate the already present local
reconciliation patch only after reconciling its guards with this design.
Existing tests and runtime edits are preserved but do not constitute acceptance
of this expanded contract.

## Acceptance criteria

After design review, validate the complete path on synthetic PostgreSQL data
with real runtime roles, verdict/assessment writers and live cover triggers:

- Null-contact/recent-poll records beside aged qualified contact; explicit
  reported states; mixed-source recovery; unknown and conflicting evidence.
- Threshold boundaries and client overrides; no invented offline duration.
- Documentation-only, stopped/archived records, retirement/restore, explicit
  confirmed use on/off, known/unknown OS and no-agent confirmed Computers.
- Profile/role/client changes, exemptions, wildcard platforms, exact entity
  identity, missing/stale transitions and superseded episode keys.
- Retained history and handling, source/identity/offline guards, suppression,
  snoozes, missing-parent detection and current-assessment recovery.
- Full and single-Computer equivalence, cross-tenant isolation, rollback,
  overlapping evaluations and source/configuration changes during a pass.
- Idempotent repeated runs and consistent stored verdict, condition, cover,
  audit explanation and relevant rendered labels.

Measure bounded query/work costs on a representative synthetic fleet and
review Docker packaging. Previously reported 148 checks describe the earlier
patch only. Testing resumed at the user's request to finish the plan; the
acceptance record identifies the executed checks and remaining limits.
Commit, push/deployment, pending migrations and production recalculation retain
their separate explicit approval boundaries. PLAN-014 remains active until
production acceptance is authorized and obtained.
