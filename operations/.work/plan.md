# Conditions integration — handoff

## Status

Issues page hotfix validated and ready to publish. Feature commit `aa4ef58`
and migration seed hotfix `502306a` reached both remotes. Migration `0161`
applied and the Operations container is healthy, but authenticated
`GET /findings/` returns
HTTP 500. The production traceback points to the Operations raw-SQL policy
loader passing a JSONB text value directly into `parse_profile`, which expects
a mapping. The ingest adapter already decodes this value when it is text.
Scope: decode JSONB text in `operations/apps/core/conditions/live.py`, add a
focused regression test, and update this checkpoint. Both JSONB result shapes
pass; 45 focused Operations tests, Django check, Ruff lint/format, compilation,
diff whitespace check, and Operations image build pass. No migration is changed
or pending for this hotfix. The deployed page still needs verification after
the approved push. Preserve unrelated edits. No manual redeploy.
Next action: publish the reviewed hotfix and verify the deployed result.

## Authority and constraints

- User requested autonomous completion and light, focused testing.
- The standing ADR-0012 rule is that domain mappings live in governed data
  with a named enforcement mechanism. The database registry, rather than a
  packaged JSON file, is the live policy authority. This is the direction
  established in the latest user conversation; do not choose a new policy
  architecture while implementing it.
- User explicitly approved: **"Approve reviewed migrations and commit/push"**
  through normal automatic deployment when implementation is ready.
- Review the exact pending Django AND ingest migrations before publication.
- **No manual redeploy.** Latest user instruction overrides the repository's
  instruction to trigger Portainer after pushing. Automatic deployment may
  apply migrations; report that distinction.
- Push approved release to origin first, then a-m-rose. Report short hash.
- No manual production migration, data rebuild, external source mutation for
  testing, or automatic device merge is authorized by this feature.
- Latest request is to update this plan for Luna's implementation; do not
  publish the unfinished draft during this planning turn.
- Preserve unrelated edits and private artifacts. Keep this plan current.
- Use focused file reads and tests; do not repeat discovery or load old journals.

## Historical worktree at the earlier handoff

- HEAD: `5922c87 Add conditions foundation and read-only shadow comparison`.
  Both remotes were verified there after the previous push, not rechecked now.
  Automatic deployment state is unverified.
- Last Django migration: `0160_source_action_requests.py`.
- Last ingest migration: `sql/migrations/108_software_evidence_view_owner_grants.sql`.
- New untracked file:
  `operations/apps/core/migrations/0161_live_condition_contract.sql`.
  No Python migration wrapper, seeds, tests, or consumer wiring exists for it.
  Django does not execute this standalone SQL file automatically.
- No new live-integration Python, template, consumer, or release changes.
- Preserve unrelated modifications to `.work/backlog.md` and
  `operations/templates/device_detail.html` (existing identity-review section).
- Preserve untracked `.work/bootstrap_intel.py` and `.work/probe_*`.
- `.work/plan.md` has a local release checkpoint and handoff pointer. Older
  sections are historical, not current instructions. Git history preserves
  earlier implementation plans.

## Goal / acceptance criteria

A shared conditions contract separates evidence, operator handling, dependency
readiness, and response eligibility across operator work, alerts, and internal
actions. A UI-only or shadow-only release is NOT completion.

1. Unsettled computer identity blocks dependent computer conclusions/actions.
   Identity repair issues remain actionable to avoid self-blocking.
2. Extended offline state pauses routine attention without resolving evidence.
   Existing shadow threshold is 180 days, not six calendar months.
3. Missing/failed/partial/stale/out-of-scope collection cannot prove absence or
   authorize cleanup. Unknown does not mean healthy.
4. Multiple typed participants are supported: computers, clients, other linked
   owned entities, source context, and global software references. Preserve
   tenant boundaries; software is not an owned Operations entity.
5. Gate software exposure per computer, not the global software fact. One
   blocked computer must not suppress eligible exposure on another computer.
6. Preserve legacy finding IDs, keys, action references, evidence and operator
   decisions. Dependency state is not another handling status.
7. Blocked/unknown/suppressed findings remain discoverable with clear reasons
   and links to blockers. Actionable counts differ explicitly from retained
   findings counts. No silent hiding.
8. No blanket critical-hides-medium rule; suppression needs a relevant
   dependency/context relationship.
9. Map ALL 53 registered types to consistent human-friendly categories, grouped
   types and individual labels. Keep technical keys inspectable by admins.
10. Eligibility supplements permissions, confirmations, exact-target checks,
    source-action leases, approvals and notification cooldowns.
11. Recovery requires valid reevaluation; stale retained evidence cannot become
    automatically actionable merely because a blocker or snooze disappeared.

## Reuse the released foundation

`operations/apps/core/conditions/`:

- `contracts.py`: immutable Condition/Participant/Signal/Decision and explicit
  EvaluationCoverage; tenant validation; stable correlation identity independent
  of handling and membership; cached participant membership.
- `policy.py`, `profile.json`: all 53 definitions, human classification,
  dependency rules, version/digest; rejects duplicate types, unknown rules,
  cycles and invalid thresholds.
- `engine.py`: pure participant-scoped eligibility; identity gate, offline
  suppression, collection gate, unknowns, operator suppression, independent
  global software facts.
- `reader.py`, `report.py`, management command `compare_conditions`: bounded
  tenant-scoped repeatable-read/read-only comparison; aggregate-only output.
  These are not live readiness authorities or production writers.
- ADR `operations/docs/decisions/0020-conditions-shadow-contract.md`.
- Runbook `operations/docs/runbooks/conditions-shadow.md`.

Prior checkpoint recorded 38 focused conditions tests passing, Django check,
no migration drift, and targeted lint/format checks for the SHADOW release.
These do not validate the new SQL draft. A broader findings test previously
failed on an unrelated existing template assertion expecting `<optgroup`;
do not repair unrelated UI solely to make that assertion pass.

## Important discovery — use, do not rediscover

### Identity

- `ingest/identity/resolver.py` emits `identity_conflict` and merge candidates.
  Findings carry `candidate_device_ids`; candidate `member_snapshots` carry
  device IDs. Same-tenant membership must be verified.
- Group review and `_merge_devices` live in `operations/apps/core/views.py`.
  Merge repoints direct findings and inventory; participant state must reconcile.
- No completed audited "these are different computers" group-review workflow
  was found. Do not treat acknowledgment/rejection alone as settled identity.
- Devices have `entity_id`; verify EntitySourceLink joins through that field,
  not an assumption that device UUID equals entity UUID.
- Proposed readiness: known client, valid source attachment, no unresolved
  ambiguity. Absence of an identity finding is not sufficient proof. The full
  readiness authority remains a design decision, not a verified implementation.
- Handle reviewed-distinct, unattached, retired and deleted cases deliberately.

### Evidence and clearing

- `observation_snapshot_runs.status` success is **complete**, not succeeded.
  See `ingest/observation_runs.py`; relevant fields are source_instance_id,
  snapshot_scope, run_started_at, completed_at, is_complete_snapshot,
  expected_rows, written_rows, failed_rows.
- Fresh complete evidence for one known scope does not prove ALL required
  scopes were evaluated. Producers must declare complete required scope,
  including multi-source negative evidence.
- `ingest/evaluator.py`: `_source_failure_guard` treats missing run history
  as healthy; `_auto_resolve` can resolve stale-agent findings when the whole
  computer becomes offline. Review both under the new contract.
- `ingest/patch_findings.py`: online scope is enforced in
  `_INSCOPE_SIGNAL_CTE`; `_auto_resolve` closes missing emitted keys as
  no_longer_actionable. Offline/unknown must not be treated as proven recovery.
- `ingest/cmdb_findings.py`: Hudu archive candidates are CLIENT-subject
  findings with exact source targets in details. A generic device-only gate
  would disable them. Establish source context/required linked-source evidence
  instead of manufacturing a device subject.
- Most finding upserts protect only open/acknowledged keys; lifecycle has a
  broader explicit update path. Avoid duplicates for investigating/suppressed
  rows without blindly widening uniqueness on unreviewed existing data.

## Implementation sequence and completion gates

### 1. Shared live contract and migration — IN PROGRESS

Affected: conditions package, new Operations migration, focused tests, ADR;
Docker packaging if sharing Python across services.

- Reuse one pure engine in `shared/conditions`; Operations and ingest import
  the same contracts/engine. Operations keeps compatibility imports only;
  remove the duplicated implementations now left below their imports.
- Make the database registry the ONLY live policy authority. A reviewed,
  frozen Git seed can populate the first version through a migration, but
  it is temporary bootstrap data, not an ongoing change mechanism. Neither
  runtime adapter may evaluate a packaged JSON profile. Keep the optional
  comparison CLI explicitly shadow-only.
- Seed all 53 registered definitions, rule effects, classifications and
  thresholds through migration data. Verify exact registry coverage and
  fail closed if a registered type, required rule, version or threshold is
  missing/unmeasurable. No hardcoded type-to-policy mapping in Python or UI.
- Version policy immutably without blocking upgrades: separate policy-version
  identity from finding-type identity, use an explicit governed active-version
  selector, record the selected version/digest on each assessment, and retain
  old rows for explanation. Operations admin users must be able to create,
  review, and activate a new validated version through a governed UI; edits
  must not require changing Git or deploying code. No silent code-controlled
  switch and no in-place mutation of an active definition.
- Read the selected policy in the same tenant-scoped DB transaction as each
  assessment/action; reject packaged-vs-DB drift and absent policy. The SQL
  adapter can differ by service, but decision rules must not be duplicated.
- Persist typed participants, assessed scope/coverage/version and response state
  separately from operator handling. Record changes sufficiently to explain
  decisions without writing an expensive history row on every heartbeat.
- Define fresh eligibility and clearing boundaries, including reevaluation after
  identity/source changes and participant reconciliation after merges.
- Enforce tenant RLS and same-tenant participants. Review function ownership,
  SECURITY DEFINER/search_path and grants. Views must explicitly revoke all DML.
- Measure indexed query/refresh cost; avoid per-finding full-inventory scans.
- Package additive migration with reviewed rollback approach. No destructive
  historical reinterpretation/backfill.

Gate: synthetic readiness/coverage/participant/RLS checks pass; migration schema
and roles verified; all definitions mapped; SQL/Python decisions do not drift.
No trigger/view/grant or seed is accepted based on static checks alone.

### 2. Producers and lifecycle

Affected: `ingest/evaluator.py`, `patch_findings.py`, `cmdb_findings.py`,
`software_findings.py`, `platform_findings.py`, `identity/resolver.py`,
`identity/client_resolver.py`, `intel/windows_servicing.py` as needed.

- Route all relevant emitters through one assessment boundary or documented
  central enforcement. Avoid separate ad hoc suppression logic per evaluator.
- Declare required scopes and successful evaluated coverage.
- Preserve evidence while blocking invalid attribution/actions.
- Never clear on skipped, partial, unknown or offline evaluation.
- Preserve operator-handled episodes and reconcile membership after merge.
- Test representative identity, offline patch, and partial-collection lifecycles.

Gate: every writer accounted for; invalid coverage cannot clear; dependency
recovery does not reauthorize stale evidence without reevaluation.

### 3. Subscribers — audit each as evidence, attention, or action

| Consumer | Entry points and required behavior |
| --- | --- |
| Notifications | `ingest/notifications.py`, both finding tables; shared selection and fresh send check; preserve rules/cooldowns |
| Digest | `ingest/notifications_digest.py`; same eligibility, retain routing intent |
| Source actions | `ingest/source_actions.py` before API; archive/retire POST and queue boundaries in Operations |
| Software exposure | `v_device_software_exposure` in ingest SQL migration 107; gate individual device exposure; preserve software approvals/evidence predicates |
| Issues/entity/patching/software pages | `operations/apps/core/views.py`, client workspace and templates; visible disposition, appropriate counts |
| Navigation/dashboard | Context processors, dashboard and client summary queries; distinguish actionable and retained totals |
| Health history | `client_health_trend_current` and refresh path; document measurement semantics, do not silently rewrite historical meaning |
| Admin Health | AdminFinding readers, source_failure/queue-health routing; source_failure has entity and admin producer paths |
| Merge/mapping | Keep repair actions available; link blockers and reconcile after decisions |
| External/legacy SQL | Preserve raw interfaces, document effective contract; legacy Agent Compliance uses a different schema and is not silently repointed |

Use `rg` for Finding/AdminFinding ORM and raw SQL readers/writers. Do not blindly
replace tables or use a default manager that hides evidence. UI buttons do not
substitute for POST/worker checks.

Gate: each native subscriber classified and integrated; representative alerts,
digest, actions and partial-exposure tests agree on eligibility.

### 4. Operator and admin surfaces

- Display retained blocked/unknown/suppressed issues, reasons and repair links.
  Add explicit response-disposition filtering.
- Count actionable rows separately without accidentally using that narrower
  queryset to hide blocked rows. CSV, table and totals must agree on scope.
- Top fleet/category cards independent of filters; second result-scope cards
  filtered. Severity breakdown uses the same clearly labeled scope.
- Reuse 53-type profile taxonomy: category -> grouped type -> individual label.
  Preserve/normalize old filter URLs. Hudu archive candidates remain findable.
- Admin inspection: technical definition, policy version/digest, participants,
  evaluated coverage, effective response/reasons. Add governed policy editing:
  an authorized admin can draft a new version, validate all 53 definitions and
  rules, review the exact changes, then explicitly activate it. Persist actor,
  time, reason and before/after version in the audit trail. Reject missing,
  duplicate, cyclic or unmeasurable rules and incomplete type coverage. Keep
  the last valid active version if draft validation fails; missing active
  authority must fail closed. This is required for the standing
  operator-maintainable-data principle, not deferred backlog work.
- Preserve existing user edits in device_detail.html.

Gate: operator can find identity blockers, Hudu candidates, suppressed patch
findings and independent software facts; labels/counts/filter semantics agree.

### 5. Focused validation and release

- Targeted contract/consumer/lifecycle tests, Django check, relevant lint/syntax,
  template load, migration state/plan and `git diff --check`.
- Execute synthetic PostgreSQL checks for new SQL/RLS/trigger behavior. Static
  SQL checks or SQLite cannot establish these contracts.
- Local Python/Ruff available. Docker CLI exists but daemon was unreachable;
  standard Program Files Docker Desktop executable absent. WSL lists
  Ubuntu-26.04 and docker-desktop; PostgreSQL availability there is unverified.
  Do not create a test service on production without explicit approval.
- Both task-owned Dockerfile drafts now COPY `shared/`; verify the package is
  present in each built image and that migration assets stay in Operations.
- Review both pending migration systems. Approved external read-only checks use
  `../Scripts/Invoke-DevTool.ps1` after reading `docs/operations.md`. Keep
  credentials/private records out of output and artifacts.
- Once genuinely integrated/reviewed, update root VERSION and CHANGELOG together,
  stage only task-owned edits, commit and push both remotes. No manual redeploy.
- Verify automatic deployment read-only when possible; report any unverified
  migration/live behavior. Mark plan complete only after actual completion.
- Do not create a follow-up commit solely to record its own hash.

## Draft defects to fix before wiring or release

- The original standalone `0161_live_condition_contract.sql` was removed.
  Its replacement Python migration has not executed on PostgreSQL; RLS,
  grants, view behavior, rollback, query cost, and role ownership are unknown.
- The migration seeds from the Operations shadow JSON into a one-row-per-type
  immutable table. That cannot represent a later policy version. Runtime
  adapters ignore the seeded table and read JSON instead.
- The subsequent untested `0161` edit added `condition_policy_versions`, but
  its trigger tests `current_user` inside `SECURITY DEFINER`; this identifies
  the function owner, not the caller, so it is not an authorization mechanism.
  `condition_policies.type_name UNIQUE` also prevents the same type appearing
  in later versions. Rework both before any PostgreSQL execution. No admin
  draft/edit/activate surface, permission boundary, or audit trail exists.
- `shared/conditions/profile.json` is a copied profile; its only current
  difference from the Operations file is a trailing newline. Remove it as a
  live authority. Preserve shadow CLI compatibility without another writable
  policy source. Update profile-path tests and migration packaging accordingly.
- Operations `contracts.py`, `engine.py`, and `policy.py` import the shared
  modules and then redefine the same classes/functions below the imports.
  Replace each with a true compatibility import; validate object identity.
- Operations and ingest assessment adapters differ in policy loading and
  response serialization. Consolidate the pure decision/coverage contract,
  leave only framework-specific persistence, and test equivalent decisions.
- No producer invokes either adapter; no consumer reads assessments. No
  identity readiness adapter, required collection-scope declarations,
  participant reconciliation, or reevaluation freshness authority exists.
- Existing `views.py` issue category/type grouping tables are hardcoded and
  overlap with profile classification. Read governed registry classification
  for category -> grouped type -> label; preserve legacy filter aliases as
  compatibility data, with explicit coverage tests rather than new literals.
- The previous handoff's identity/evidence/CMDB defects still apply. The
  current draft did not fix them. Do not call it live-ready or publish it.

## Cost-conscious handoff recommendation

Luna Medium can handle bounded implementation tasks once contracts are settled.
The shared readiness authority, tenant/RLS migration, and final cross-consumer
review remain judgment-heavy. Prefer a balanced model for those gates rather
than asking Luna Medium to autonomously approve the whole unfinished design.
This is a recommendation, not a new restriction on the user's approval.

## Luna execution order

1. **Stabilize the shared package.** Verify Git status/diffs first. Keep
   unrelated `.work/*` files and the user's `device_detail.html` edit. Make
   Operations compatibility modules import only shared objects. This change
   has been drafted locally, not validated. Keep shadow reader/report in
   Operations. Verify class and function identity across import paths and
   Dockerfile packaging. Confirm there is one packaged profile path and no
   duplicate live policy reader.
2. **Rebuild policy authority before any consumer gate.** Inspect existing
   `finding_types`/category and policy-governance patterns. Rework the
   task-owned `0161` migration into additive, versioned policy/assessment
   storage with a governed active version. Freeze the reviewed seed used by
   the migration; validate 53/53 registry matches, schema/version/digest,
   rule graph, thresholds and classifications. Both service adapters load
   selected policy from DB under tenant context, never from local JSON.
   Retain the released shadow CLI's explicit profile input as comparison
   input only. Build Operations admin draft/review/activation as part of this
   gate: authorization, immutable new versions, explicit active selection,
   diff preview, actor/reason audit, fail-closed validation and rollback to
   the last valid active version. Prefer existing admin/permission/audit
   patterns; do not invent a second policy authority. Document the durable
   authority and update mechanism in a new Operations ADR.
3. **Verify policy/storage gate on PostgreSQL.** Use a disposable local or
   approved isolated PostgreSQL environment, not production test writes.
   Test seed, admin draft/edit/activate/permission/audit, upgrade selection,
   invalid-draft rejection, missing-policy failure, same-tenant typed
   membership, RLS under runtime roles, denied DML on views, grants, rollback,
   and indexed refresh/query cost. Review `SECURITY DEFINER` ownership and
   `search_path`; avoid one expensive inventory scan per finding. Do not
   proceed to enforcement if this gate cannot be established.
4. **Wire one producer assessment boundary.** Route each relevant ingest
   emitter through the same typed participant/signal/coverage contract.
   Identify all Finding/AdminFinding writers with `rg`; maintain a checklist
   in this plan until every writer is classified. Declare ALL required source
   scopes for negative evidence, including Hudu client-subject cleanup and
   multi-source absence. Use `status='complete'`, expected/written/failed
   counts, freshness, future-time checks, and exact scope. Missing history
   remains unknown. Guard every automatic clear/resolve path; skipped,
   partial, offline and stale cycles retain evidence/handling. Reconcile
   participants and invalidate assessments after merge/mapping/source changes.
5. **Wire subscribers at their real boundaries.** Notifications/digest use
   fresh eligibility before routing and cooldown; source-action POST/queue
   and worker recheck before external API; software exposure gates each
   device association while preserving global facts. Issues/Admin Health,
   entity pages, navigation, dashboard and CSV show retained findings and
   separate actionable counts, reasons and blocker links. Replace hardcoded
   issue taxonomy with governed policy data while maintaining old URL aliases.
   Health-history semantics and external SQL compatibility must be explicit.
6. **Validate and release only when integrated.** Run focused policy-admin,
   lifecycle,
   subscriber and partial-exposure tests, Django check/migration-state review,
   SQL/RLS checks, relevant Ruff/syntax/template checks and `git diff --check`.
   Review the exact pending Django and ingest migration lists and migration
   effects. Update root VERSION/CHANGELOG together only for a ready release.
   Stage only task-owned files. Existing user approval covers reviewed
   migrations and commit/push to origin then mirror when ready; no manual
   redeploy. Verify automatic deployment read-only if available and report
   limitations. Mark this plan complete only after real validation.

At each gate, update status, confirmed validation, decisions, checkpoint and
next action here. If a gate exposes a new architectural conflict, surface the
exact competing authorities to the user rather than inventing a rule.

## Current checkpoint / next action

The live contract, versioned database policy authority, producer and
subscriber gates, Operations admin policy surface, and retained-finding UI
are implemented. Issues and Admin Health now show persisted assessment
dispositions, reasons, blockers, policy version, and an explicit pending state
when legacy rows have no assessment. Hudu stale findings use source-binding
participants and retain their client subject; their clearing lifecycle is
assessment-gated after migration and compatibility-guarded before it.

Validation completed: disposable PostgreSQL migration/seed/RLS/grant and
policy lifecycle checks pass (3 tests), focused contract/lifecycle/Windows
checks pass (60 tests when run from the repository root), Operations queue
checks pass from `operations/` (13 tests), Django check and migration-state
check pass, targeted Ruff/import checks pass, Python compilation passes, and
`git diff --check` reports no whitespace errors. The Operations image builds
with the shared package and migration packaged. The Dockerized software
validation environment has pydantic 2.9.2; the focused software checks pass
(39 tests). One unrelated pre-existing read-model test still fails because its
fake cursor does not accept SQL parameters after the test reaches existing
`run_log` code; no source change was made for that failure.

The approved read-only production check still reports Operations migration
0160 and no condition policy tables; 0161 has not been run manually. No
production or external source writes were performed.

The automatic startup failure was corrected by `502306a`. Migration `0161`
applied and Operations health passed on the automatic retry. No manual
redeploy occurred.
