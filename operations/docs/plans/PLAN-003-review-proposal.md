# PLAN-003 — Findings review and consolidation proposal

Current contract: [PLAN-003 current design](PLAN-003-current-design.md).
This report retains discovery, primary-source evidence and superseded proposals;
its historical Next statements are not the current handoff. Use the current
design and BLUEPRINT for decisions and remaining work.

Status: partially accepted design proposal, 2026-10-27. No implementation or migration execution
is approved. The [requirements checklist](PLAN-003-issues-page-design.md)
retains the earlier accepted page decisions. This report proposes amendments;
it does not silently replace those decisions. The registry owns plan status.

## Evidence and limits

Review covered historical PLAN-003 requirements, current producers, registry,
condition/state handling, queue readers and actions, and an aggregate production
snapshot for one tenant. The external snapshot used a repeatable-read,
read-only transaction through the shared validation helper. No customer-level
records or credentials are included here. Counts below describe that snapshot,
not a continuously current dashboard or an all-tenant certification.

- 71 registered types; 38,509 active entity findings and 363 active admin
  findings, totaling 38,872. These are raw active rows, including paused and
  covered records, not the default visible queue population.
- 32,263 raw Pending states: 29,325 fresh incomplete assessments, 28 stale
  incomplete assessments, 181 fresh no-current-assessment states and 2,729
  stale no-current-assessment states. These labels do not prove missing data.
- 2,935 raw Covered states, of which 2,461 were stale or missing current
  assessment freshness. Current readers can translate stale state to Pending;
  cover validity must not be conflated with child assessment freshness.
- 34 fresh evidence-blocked states. This is evidence of engine gating, not
  proof that an operator has no useful review action.
- No UUID collisions within the reviewed tenant, exact active cross-ledger
  `(tenant, type, condition_key)` matches, or duplicate active entity condition
  keys were found. Semantic duplicates remain possible.
- 21 types are alertable. This does not establish that notification delivery is
  enabled or authorize enabling it.

Production aggregates corroborate opportunities and risks; they do not prove
that overlapping rows should be merged. Browser behavior, latency, all consumer
compatibility, and migration feasibility have not been validated. Historical
reviews of 53 or 63 types are not the current inventory.

## 1. Remove generic Waiting and operator Blocked

Recommendation: remove Readiness from operator filters, subgroups, row columns,
count breakdowns and default sorting. This explicitly amends earlier accepted
Readiness controls and requires user approval. Retain Status
Open/Paused/Resolved, Severity, specific next actions and concise evidence age.
Priority remains ordering, not another stored field or a rename of Severity.

The current Pending population largely describes assessment bookkeeping, not
an operator workflow. Removing its label must not automatically enable actions
or call every row actionable. Preserve evidence freshness, identity, permission
and execution guards. A Review action can remain useful while a particular
mutation is unavailable; explain that guard beside that action.

Use a concrete finding for a real problem instead:

- Required source information is absent: identify the missing field/source,
  exact scope, effect and repair action. An unknown OS preventing a coverage
  decision can be an explicit data-health finding.
- Evaluations are not being completed: an evaluation-health finding describes
  the failed evaluator/run or configuration at its actual scope. Do not create
  thousands of identical child tasks merely because assessments are absent.
- A genuine prerequisite exists: link the exact prerequisite finding. Retain
  the independent child when its condition is established; gate only affected
  actions. Do not assert or clear a condition from untrustworthy evidence.
- Deliberate deferment remains Paused, with reason and expiry. Expected job
  dependency waiting remains job state unless it violates an operational rule.
  No second generic waiting status is justified by the reviewed cases.

Missing required data can be more severe than its dependent symptom, but
severity follows demonstrated impact, scope and duration. A missing field or
assessment alone is not automatically High/Critical. Known security risk must
not disappear merely because new telemetry is unavailable.

Proposed replacement ordering: severity first for group selection; registry
order breaks equal-severity group ties. Rows within a severity subgroup use
latest detection then stable identity. Software approval retains its accepted
affected-Computer ordering. Keep Flat, Category → Type, and optional Severity
subgroups. Drop the Readiness subgroup option if this amendment is accepted.

## 2. Covered means hidden from independent work

A validly covered symptom is not independently actionable. Hide it from normal
rows and normal actionable counts even when filters exclude its parent. Do not
reveal it as an independent result to compensate for a filtered-out parent.
It remains accessible from parent Related issues, direct detail and history;
explicitly identify it as covered there. Severity totals must disclose whether
they count independent work or retained related evidence, without double counting.

Continue evaluating it. When cover is no longer valid, re-evaluate and restore
it if still unresolved. Parent closure or pause is not proof of child resolution.
Assessment expiry alone must not uncover a still-valid relationship; invalid
relationships must not suppress work indefinitely either. The common projector
must decide relationship validity from the applicable current evidence.

Use one expandable `Related issues (N)` area with per-child descriptions:
`Covered by this issue` or `Requires this issue first`. The second relationship
does not hide an independently established problem. Keep counts of those two
kinds distinct inside the expansion. Do not use the rejected label Explained.

## 3. Findings inventory and consolidation recommendations

The following inventory assigns all 71 reviewed registry types to 17 review
families. These are analytical families, not replacement queue categories or
new registry membership. The five accepted category names remain unchanged.
Workspace reuse does not imply a merge of conditions or a new bulk action.

| Family / registered types | Recommendation and resolution surface |
| --- | --- |
| F01 — `client_name_conflict` | Preserve accepted ADR-0040: one name-difference finding per client with source-group evidence, resolved through existing client review; distinct from source-group assignment. |
| F02 — `client_link_collision`, `client_source_group_merge`, `client_unattached_group`, `unnamed_source_group`, `unmatched_source_group` | Accepted: same-source-group warnings that ask the same ownership question and share one corrective mapping decision become one issue. Missing-name/collision evidence joins that case only if the same decision settles it. Separate source repairs retain separate work. Verify exact scope/action before conversion; no blanket type merge. |
| F03 — `identity_conflict`, `duplicate_device_records`, `shared_serial`, `computer_name_collision` | Follow accepted ADR-0043: consolidate these four plus two_machines_on_one_computer into One machine or two?, one case per connected Computer group with evidence-specific merge/separate/split actions. Production group/scope measurements are still a prerequisite; PLAN-004 owns detection and repair. |
| F04 — `duplicate_platform_record`, `computer_client_conflict`, `two_machines_on_one_computer` | ADR-0043 keeps duplicate_platform_record separate as source hygiene and includes two_machines_on_one_computer in the unified identity case. ADR-0040 separately consolidates client ownership into computer_client_conflict. The earlier recommendation to retain all three separately is withdrawn. |
| F05 — `computer_name_differs_in_source`, `device_role_conflict`, `lifecycle_reported_state_conflict`, `lifecycle_unknown_reported_state`, `unmapped_node_class`, `source_name_kind_unclassified` | Blanket lifecycle aggregation proposal withdrawn. Current unmapped_node_class is already one admin finding per unmapped value, and source_name_kind_unclassified per platform/record type; lifecycle_unknown_reported_state is Computer-specific. A shared lifecycle mapping fix has not been established. Preserve existing distinctions unless specific cause/action equivalence is verified. |
| F06 — `device_missing_from_source`, `device_offline`, `device_stale_data`, `archived_but_reporting` | Accepted offline/stale-data boundary: distinguish device last contact from platform observation freshness. Proven collection failure covers matching stale-data symptoms; no automatic offline→stale-data cover or collection-failure→offline cover. Retain known independent offline issues and guard new offline conclusions under stale evidence. No agent-applicability/threshold change. Source disappearance and archived-but-live conditions retain their specific lifecycle/repair meaning. |
| F07 — `missing_required_platform`, `stale_required_platform`, `device_unenrolled`, `os_unknown_coverage` | Accepted direction: retain unexplained no-agent cases as one Computer inventory/lifecycle review, not an installation requirement; title Computer without agent evidence. Expected cases get a reasoned recorded disposition; established lifecycle/identity/requirement issues own their repair and cover duplicate review work. Preserve recognized-OS applicability; no blanket type retirement or universe expansion. Recognized-OS evidence below supersedes the earlier gap interpretation. |
| F08 — `cmdb_asset_stale`, `cmdb_link_incorrect`, `unintegrated_source_observed` | Accepted archive/link boundary: per-asset/condition findings, verified duplicates only, exact-target freshness guards and independent link correction. Hudu-only lifecycle work stays with device_missing_from_source/documentation_only. Preserve an actionable integration-gap administrative task with verified configuration scope; collector provenance alone is insufficient. Recommend zero replacement/coverage of the 102 lifecycle cases by this integration-gap signal; extra visibility is not causal repair. |
| F09 — `rare_recent`, `whitelist_suggestion` | Clarified direction accepted: one administrative Software approval pending case per product, describing uncovered installations with rarity/recency/prevalence evidence. Preserve global/client/Computer decision scopes and separate actual Computer/installation risks. Approval does not automatically settle those risks. October 14 explicit merge request and later deferral are documented below; conversion must preserve IDs/history/references through reviewed mappings. |
| F10 — `capability_review_candidate` | Accepted: one product/capability judgment with combined source evidence; existing Confirm/Reject actions and permissions. Separate from software approval, authorization and requirements. Different capabilities remain distinct judgments. Existing handler already deduplicates targets at product + capability scope. |
| F11 — `unauthorized_remote_access`, `unauthorized_av`, `unauthorized_rmm`, `rejected_software_installed` | Group authorization review by product and decision scope with affected Computers. Preserve client exceptions and per-installation actions. Known rejected software remains a policy-breach condition, distinct from an undecided title. Reuse software authorization review. |
| F12 — `suspicious_name`, `install_path_suspicious`, `known_malicious_hint` | Accepted boundary: show relevant risk evidence during approval review without absorbing or resolving independent risk findings on approval. Installation remediation remains scoped to its installation; threat-report matches require investigation and are not confirmed infection. Apply existing per-type decision semantics; no blanket approval suppression or type merge. |
| F13 — `vulnerable_software`, `eol_runtime` | Accepted: keep version-specific security/support conditions separate from approval. Same product alone does not prove same problem/repair. Reuse product/version exposure review. |
| F14 — `device_never_patched`, `patching_stalled`, `patch_approval_backlog`, `patch_failing_repeatedly`, `reboot_pending` | Accepted: retain existing scope/condition distinctions (never/stalled already mutually exclusive, failures per update/Computer, backlog client-scoped, reboot a distinct action). Proven same-root fallout becomes impact/covered evidence, e.g. an update failure explaining stalled progress. No blanket family merge. Reboot prerequisites need evidence, as previously agreed. |
| F15 — `windows_servicing_approaching_eol`, `windows_servicing_eol`, `windows_servicing_unknown` | Accepted: preserve alternative lifecycle states/types; no grain/type consolidation justified. Verify prior-stage retirement and history on transition. Unknown requires evidence investigation, not a presumed upgrade. ADR-0016/current projector supply state authority. |
| F16 — `source_failure`, `software_queue_stalled`, `stale_collector_binding`, `software_inventory_held`, `jobs_schedule_failure`, `jobs_required_disabled`, `jobs_queue_backlog`, `jobs_repeated_failure`, `jobs_timeout`, `jobs_registry_mismatch`, `jobs_unmet_dependency`, `change_history_unclassified` | Consolidate proven same-incident symptoms by exact job/run/source scope, retaining attempt history. Expected dependency waiting is job state; classify the 244 active unmet-dependency rows before retiring anything. Registry/configuration and held inventory problems can require separate repairs. Reuse Jobs and source health review. |
| F17 — `device_source_record_withdrawn`, `cross_client_conflict`, `cross_client_serial`, `device_long_offline`, `multi_av_conflict`, `placeholder_serial`, `placeholder_mac`, `identity_resolution_pending`, `unlinked_external_identity` | Mixed historical, disabled, synthetic and quiet types: preserve history; do not retire a type simply because active count is zero. Candidate work remains in the queue read contract without fabricated canonical findings. PLAN-004/021 retain identity/candidate repair. |

Two especially important safeguards:

- Authorization volume is not evidence of legitimacy: remote-access rows span
  119 titles and 445 client/title combinations; AV rows span 38 titles and 70
  combinations. Do not globally approve vendors to clear the queue.
- Overlap is not causality. There are 433 Computer overlaps between missing and
  stale required-platform findings, and 148 between patching stalled and reboot
  pending. Validate the exact platform/requirement and remediation. In particular,
  a reboot can remedy stalled patching; stalled patching does not necessarily
  cover the reboot task. Recommend removing that cover unless a specific rule
  proves equivalence.

Current offline cover rules and severity demotion also conflict with the older
principle that a never-installed required agent remains a real gap even offline.
Review those pairs explicitly, particularly security requirements. Do not carry
an accidental suppression rule into the new model as an approved policy.

Potential episode-grain issues also need proof: 540 unenrolled findings concern
402 subjects; 970 offline findings concern 963. Multiple requirements can be
legitimate. Mutable client context in condition keys is a possible contributor,
not a measured cause. Audit before changing identity or merging history.

## F09 correction — historical workflow distinction

The user challenged the proposed merge before accepting it. No F09 merge is
approved. The earlier recommendation treated shared approval behavior as proof
of the same task and omitted the historical workflow distinction.

Primary conversation located: local Codex session
`rollout-2026-08-11T12-33-12-019ff1ab-bc39-7b81-8191-3ad82fddc7f6.jsonl`,
lines 2541–2613, 2026-08-11 23:11–23:16 UTC. The user said the generic actions
did not make sense for whitelist suggestions, asked to preserve documented
prior work, and emphasized global/client/device approval scopes. The response
distinguished title-level policy review from device incidents and reused
SoftwareDecision rather than generic finding-state actions. The user then
authorized that scoped implementation in that historical session; that old
authorization does not authorize current implementation, commit or deployment.

Corroborating implementation:
[736251b — Separate policy candidates from actionable issues](https://github.com/chamayer/ninja_dashboard/commit/736251b0c8d9fe77a9d5522243e788689f45b804).
Its plan explicitly calls whitelist_suggestion an undecided widespread title,
not a device incident; authoritative actions are existing scoped software
decisions. The historical archive also explicitly excludes rare_recent from
the subject migration because recency was a per-device fact
(`docs/archive/workspace-cleanup-2026-10-20/plan.md`, former step-3 scope).

Later conflicting evolution must also be surfaced: accepted ADR-0030,
2026-10-13, section 2 puts rare_recent at product grain, and section 8 retains
distinct rare/non-approved types split by prevalence. Commit
[dd44ae4 — Raise rare software per title](https://github.com/chamayer/ninja_dashboard/commit/dd44ae4dc1a39695394262861bd0a274afb26d14)
implements migration 0284 and resolves old device findings as subject_regrained.
This corroborates a later semantic change, not approval to merge the types.

Next definition must distinguish the policy decision from the actual
Computer/installation condition, identify each owning action and lifecycle,
and reconcile the later product-grain implementation with the user's clarified
intent. Preserve the two meanings pending that review. Do not restore separate
queue sections merely because their workflows differ.

Later primary conversation found during the renewed review: local Claude
session `ce7eb61f-3320-4dc2-8589-52a52e090f9c.jsonl`, 2026-10-14 16:33–17:03
UTC, lines 5219–5317. The user asked to discuss the suggestion and rename
whitelist toward approval. The assistant explicitly offered display rename or
merging rare_recent and whitelist_suggestion; at 16:42 UTC the user replied
"merge but is the suggestion logic sound? and where will the count be displayed
(can it be part of subject?)". Later "yes build it" accepted the evidence helper.
The archived backlog separately deferred the roughly 15,000-finding re-key
merge. This is a later explicit merge instruction, not merely an assistant
suggestion; the earlier review missed it.

Current `software_reconcile.py` still creates separate product findings at the
rare boundary. October 22's per-installation coverage change (ADR-0039 remains
Proposed in its header; corroborating implementation exists) narrows prompts
to uncovered installations without restoring Computer-grain rare findings.
Thus an approval prompt and a Computer-specific risk remain different work,
while these two current prompt types are prevalence variants of product-level
approval work. Proposed reconciliation: follow the explicit merge direction
with one administrative approval case, affected/uncovered installations and
rarity/recency as evidence; preserve actual unauthorized Computer and suspicious
installation conditions separately with their owning actions. Do not silently
restore device-grain rarity or erase old episode history. Present this clarified
mapping to the user before implementing the consolidation. The user has now
accepted this clarified direction: one administrative approval case per product,
uncovered-installation evidence and existing decision scopes, with independent
Computer/installation problems retained and history preserved. No implementation
or data conversion is authorized by that design acceptance.

## F03/F04 correction — an accepted identity consolidation already exists

The latest proposal to keep duplicate-device and two-machines-on-one-Computer
findings separate missed accepted ADR-0043. It is withdrawn, not an alternative
approved direction. Historical evolution:

1. ADR-0032 distinguished findings by evidence/condition and supplied merge,
   separate, split and source cleanup actions. ADR-0034 refined naming evidence.
2. ADR-0040 consolidated client ownership into Computer under the wrong client?
   (`computer_client_conflict`), replacing cross-client serial/conflict findings.
3. [ADR-0043](../decisions/0043-one-machine-or-two.md), accepted 2026-10-23,
   consolidates duplicate_device_records, identity_conflict,
   computer_name_collision, shared_serial and two_machines_on_one_computer into
   One machine or two?, one finding per connected Computer group. Evidence rows
   support merge, confirm separate and split; strong two-machine evidence blocks
   merge. Duplicate_platform_record remains source hygiene; client ownership
   remains with ADR-0040. Measure resulting groups and verify client boundaries
   before building. Existing decisions and recorded/reversible actions survive.

Authority caveat: ADR-0043's subsection still says Decision (proposed), but its
Accepted header is corroborated by the module checkpoint (accepted, build waits
for production measurements) and commit
[0c812db](https://github.com/chamayer/ninja_dashboard/commit/0c812db74e9a398fbe1f32a80db85c69f216f023),
which explicitly records acceptance. Do not treat the stale subsection heading
as a new approval gate or equate accepted design with shipped implementation.
This review has not established that consolidation is implemented. The user
subsequently agreed with following this decision, including separate client
ownership/source hygiene and safe group boundaries.

PLAN-003 should consume the agreed identity case rather than invent a second
consolidation design. Coordinate its shared finding/relationship contract with
PLAN-004; do not silently broaden PLAN-003 into identity algorithm execution.

## F07 verification — no-agent findings versus requirement coverage

Requested by the user after challenging the hypothetical enrollment decision.
Read-only production verification on 2026-10-27, 16:30–16:33 UTC, tenant 1;
each snapshot used repeatable read, transaction_read_only=on and explicit
tenant context. Queries returned aggregates only. No refresh, evaluator run,
finding write or source action was performed. Counts concern active raw finding
statuses (open/acknowledged/investigating), not visible queue totals.

### Confirmed mechanism

- `ingest/evaluator.py` `_evaluate_coverage` applies existing client/default
  profiles and overrides, but only enters its coverage universe with an agent
  presence row or explicit `in_use_confirmed=true` decision. Outside that
  universe it records `outside_coverage` and skips both missing-agent evaluation
  and the later unknown-OS finding path. ADR-0035 documents this boundary.
- `_evaluate_unenrolled` independently finds non-retired Computers tracked by
  active vm.guest/vm.host/network.device/monitor.target observations with no
  agent presence. It does not determine that requirements are undecided, apply
  requirement exemptions, or require fresh tracking/powered-on evidence.
- Its existing review opens Computer/source context. The registered Still in
  use action is restricted to device_missing_from_source, not device_unenrolled.
  This review found no corresponding dedicated enrollment-policy decision
  action. The earlier invented "decide whether Ninja is required" workflow
  therefore remains unsupported; profile policy already exists.

### Measured population

540 active unenrolled rows concern 402 distinct Computers. Current metadata
reproduces the detector's active-tracking/no-agent/non-retired qualification
for 309 Computers, including all such current subjects in this tenant.

| Disjoint group among the 402 subjects | Computers | Interpretation |
| --- | ---: | --- |
| Current detector match, active/offline_aging lifecycle | 87 | Distinct current no-agent population outside retirement cleanup; none has an active missing-required-platform or os-unknown-coverage finding. |
| Current detector match, pending_cleanup lifecycle | 222 | Still qualifies for unenrolled but lifecycle cleanup may own the actual review; independent enrollment action is not established. |
| Already retired | 48 | Cannot currently be emitted by this detector; 89 retained active finding rows remain on these subjects. |
| Agent presence now exists | 11 | Current no-agent predicate is false; resolution freshness/assessment gates must be investigated before closing anything. |
| Non-retired, no agents, but qualifying tracking ceased | 34 | Current no-agent tracking predicate is false; retained active rows need lifecycle/closure investigation. |

The 87 non-cleanup Computers have 178 active unenrolled rows. Of them, 85 have
unknown OS and 2 Windows. Latest stored unenrolled evidence reports powered-on
VM observations for 76 (74 unknown OS, 2 Windows), plus 8 VM-host, 2 network and
1 monitor-target observations. Current tracking metadata was received recently;
stored power state is evidence, not proof an agent can or should be installed.

A concrete policy-defined case exists: one Windows workstation has stored
Ninja, SentinelOne and LogMeIn requirement verdicts, all outside_coverage,
despite an active unenrolled finding. The other Windows subject, a server, has
an R-U-ON requirement verdict outside_coverage. Neither is proof of an unknown
policy decision. These are existing requirements bypassed by the universe
boundary. No customer identifiers are retained in this report.

There are 138 excess rows beyond one unenrolled row per subject, on 10
Computers. All finding client copies match their current Computer in this
snapshot, so client-copy mismatch is not an established explanation. Episode
and merge history require separate audit; do not assume all rows can simply
be deleted. Across the broader population, some existing missing findings
coexist with outside_coverage verdicts; that overlap is not proof of equivalent
current repair tasks. Fresh stored verdicts were about 30 minutes old.

### Conclusion and proposed follow-up

The population is distinct from requirement findings, but that alone does not
establish actionable missing-agent work. The initial recommendation to widen
the coverage universe was premature: the user requires recognized OS instances,
not hardware or a VM shell. The follow-up below verifies this distinction and
supersedes the earlier interpretation of these 87 subjects as a coverage gap.
PLAN-014 owns applicability; identity/lifecycle coordination is required for
OS-link and retained-finding repairs. No correction or retirement is authorized
by this read-only verification.

Limits: one tenant, point-in-time aggregates; no customer-by-customer decision
review, browser inspection, evaluation rerun or causal episode-history audit.
The exact registered/action gap and SQL/code behavior were inspected; this is
not a claim that the proposed remediation is implemented or validated.

### Recognized OS versus hardware — follow-up verification

User constraint: require agents only for recognized OS instances, not empty
hardware or VM shells. Read-only repeatable-read tenant-1 production checks on
2026-10-27, 16:57–17:00 UTC, compared canonical installation relationships,
source identities and safe observation metadata, without modifying state.

Accepted ADR-0013's 2026-09-08 amendment and `ingest/os_installations.py` define
the existing mechanism: stable agent-record identity establishes a canonical
OS installation; vm.guest is Computer evidence and does not establish an OS
installation. `operating_system_installations` plus the effective dated
`os_installation_runs_on_computer` relationship is the canonical contract,
exposed by `v_computer_os_installation_current`. A retained Computer OS label
is not equivalent. The legacy `os_instances` projection can open a row merely
because form factor is physical/VM, and is explicitly not a canonical anchor.

Results for the 87 current non-cleanup no-agent subjects:

| Evidence | Computers | Conclusion |
| --- | ---: | --- |
| Unknown OS, no canonical OS relationship, legacy OS row present | 74 | A compatibility row does not establish an installed OS. |
| Unknown OS, neither canonical relationship nor legacy OS row | 11 | No recognized OS installation established by these records. |
| Windows cache label and canonical OS relationship present | 2 | Follow-up source correlation finds inconsistent attachment; not a validated missing-agent case. |

For those last two, all nine correlated agent source identities have current
active observations attached to other Computers, not the no-agent Computer.
Their effective runs-on relationships were last projected 2026-10-21. This
establishes a discrepancy between the relationship and current source attachment,
not its cause or a safe repair. An intentional operator relationship decision,
move/reconciliation history and projector behavior must be checked before repair.
Neither the Windows cache label nor the active edge alone justifies installing
agents on those two Computers.

The canonical projection is populated: 5,234 installation anchors and 5,025
current relationships across 4,996 Computers in this snapshot. Within the wider
402-subject unenrolled population, eight now have active agent observations but
no current canonical OS relationship, another consistency question rather than
proof that the legacy projection can replace the canonical one.

Conclusion: the model distinguishes recognized OS installations from hardware
inventory, but the existing unenrolled detector does not use that distinction;
it can flag VM/hardware-only evidence. No valid missing-agent installation task
was established among these 87. Keep the recognized-OS applicability boundary,
withdraw the proposed blanket universe expansion, and investigate the two
inconsistent OS links separately. Review whether generic unenrolled findings
have any independent actionable role before retiring/mapping them; do not turn
absence of recognized OS evidence into a new install or enrollment task.

Limits: unrecognized is not proof physically empty; sources may lack evidence
of an OS that actually exists. No customer-level source payloads or secrets were
printed. Raw effective-attribute SELECT was denied by the runtime role, so no
privileges were changed; verification used authorized OS and metadata projections.
No projection refresh, relationship repair or evaluator run was performed.

### Consolidated recommendation after user clarification

Accepted after clarification: retain the investigation task for unexplained
no-agent cases, but stop describing it as an enrollment or missing-agent
requirement. Title: Computer without agent evidence, under
Inventory/lifecycle review rather than Required agents. Review is the action,
not part of the title; finding titles name conditions rather than instructions.
The user subsequently moved to the next decision, accepting this direction;
implementation and live finding disposition remain unapproved.
This does not assert
that the record exists in only one source; the review must compare all relevant
source, identity and lifecycle evidence.

One review per Computer establishes whether it is expected inventory, a
decommissioned resource, or a current machine with incomplete/incorrect
evidence. Expected hardware/VM/template/unmanaged cases receive a recorded,
reasoned disposition using the existing applicable decision/override contract;
do not repeatedly raise the unchanged accepted condition. Decommissioning uses
the lifecycle workflow after evidence review; no automatic retirement. In-use
cases investigate source matching and supported OS recognition; only a properly
recognized OS enters applicable agent checks. If an existing lifecycle, identity
or specific requirement issue already owns that same repair, it owns the work
and the generic review is covered rather than another independent task.

The detector must distinguish unexplained review from expected absence rather
than infer a fault from no-agent evidence alone. Before implementation specify
that eligibility/disposition contract, changed-evidence reopening and audit,
and guarded review/action routing. Existing 48-retired/11-now-agent/34-no-tracking
subjects and 138 extra rows require verified disposition/history mapping.
This is the accepted design direction; earlier recommendations for unconditional
retirement or blanket installation requirements are withdrawn. No application,
schema or live finding changes have been made.

## F08 verification — Hudu-only Computers versus integration hints

User requested a grounded recommendation after discussing 100 records coming
only from Hudu. Read-only repeatable-read tenant-1 snapshots on 2026-10-27,
17:23–17:26 UTC compared current source lifecycle metadata, canonical Computers
and active raw findings. No private record identifiers/names or payloads were
printed; no evaluator/refresh or data mutation ran.

### Existing authority and measured behavior

- Accepted ADR-0032 explicitly assigns a Computer with only current Hudu
  documentation to `device_missing_from_source`, reason `documentation_only`,
  with one finding per Computer. `ingest/computer_listing.py` and
  `_evaluate_device_lifecycle` implement this. The review determines whether
  documentation is obsolete or the Computer is still in use. Source withdrawal
  is history, not a second independent issue for each missing source.
- 140 current Hudu assets represent 102 non-deleted canonical Computers with
  current Hudu documentation and no other current source record (excluding
  device-health rows). All 102 are pending_cleanup and already have one active
  documentation_only lifecycle finding each. Multiple Hudu assets therefore
  do not multiply lifecycle issues. No separately active cmdb_asset_stale
  finding targets these same current assets in this snapshot.
- Other historical/risk findings remain on some of these Computers, including
  37 unenrolled rows across 32 of them. Co-occurrence does not automatically
  explain every independent risk. Generic no-agent review should be covered
  where the existing lifecycle finding owns that same investigation, consistent
  with the accepted root-issue rule and F07 direction.
- Source-only Hudu records are a different population: metadata includes 4,253
  unlinked, unarchived, unrestricted active asset records without an attached
  Computer, plus nine restricted records. Those counts are assets, not verified
  Computers. Do not fabricate canonical Computers or lifecycle tasks from them;
  applicable existing asset/matching work retains its own scope and permissions.
- The 78 active unintegrated_source_observed findings concern 77 clients and
  two vendor labels, carrying 3,624 record mentions (not unique Computers).
  `_UNINTEGRATED` groups Hudu relay metadata by client/vendor. The collector
  sets integrated from its supported vendor set (currently Ninja), not by
  verifying an expected connection is configured or failed. Thus the flag is
  not proof of a missing/broken integration or that the Computer exists only
  in Hudu. Original migration 0091 describes a suggestion to consider direct
  integration, not a demonstrated repair condition.
- Two active Ninja source-failure findings also exist. This check did not
  establish that they caused the 102 documentation-only cases. Shared vendor
  or simultaneous presence is not a causal link; do not convert 102 decisions
  into one assumed integration incident.

### Firm recommendation (proposal awaiting acceptance)

Keep the established lifecycle model: for 100 verified Hudu-only Computers
whose status needs a decision, keep 100 per-Computer lifecycle work items,
presented through the existing counted group and a scoped review workspace.
Show each Computer's source/last-contact/history and all linked Hudu assets
together. Reuse applicable authorized actions; multi-selection does not
authorize a blanket archive/retirement. No extra queue section or row expansion.
Hudu-only evidence does not establish an agent-installation requirement.

If evidence proves one shared source failure explains the apparent absence,
that source issue owns the repair and matching Computer symptoms are covered
until reassessment. Otherwise each Computer can have a different disposition;
one common provenance label is not enough to merge their lifecycle decisions.

Preserve the integration-gap signal as administrative work when a concrete
integration decision/configuration gap is established. Suggested title: Source
not directly integrated, one issue per actual decision/connection scope, with
affected client/asset counts. Verify against configured source identities;
the collector's supported-vendor flag is insufficient. Record intentional
indirect collection as a reasoned disposition, rather than endlessly raising
unchanged hints. Provenance remains visible on records. This revises the
earlier recommendation to remove the signal entirely; no new connector or
notification delivery is authorized.

Integration-gap versus the 102 lifecycle findings: recommend zero replacements
or cover links based on this signal. Adding visibility is not proof of the
cause of a Computer's absent existing-source records. Follow-up read-only
snapshot at 17:33 UTC found 132 unarchived Hudu records labeled linked (98
Computers) and five divergent (five Computers, one overlapping the first set).
Both verdicts come from supported Ninja record lookup in the collector, not
the unintegrated-vendor branch. Inactive Ninja agent records remain for 80 of
these Computers and VM records for 47 (overlap allowed). No missing integration
was established as the cause of their current absence. Their lifecycle/source
matching decisions remain independent of integration-gap administrative work.
A separately proven failure of an existing source is still subject to the
accepted causal cover rule; it must not be conflated with adding an optional
or missing integration.

Limits: one tenant and point-in-time aggregates; no operator disposition of the
102 cases, shared-failure causality, browser/permission acceptance or source
actions were validated. This is design evidence and a recommendation, not an
implemented lifecycle repair or retirement of the hint type.

## 4. One authoritative findings store

Proposal: extend existing `operations.findings` and migrate admin findings into
it, rather than create a third active ledger. Preserve UUIDs where possible and
provide a deterministic legacy `(row_kind, id)` mapping for every old reference.
The one-tenant collision check does not replace a full migration preflight.

The common contract needs tenant, type, stable subject/scope, client context
where applicable, condition/episode key, evidence and provenance, severity,
lifecycle, pause, first/last detection, closure, version and audit references.
Represent noncanonical source/job/configuration subjects with a validated typed
reference. Do not invent canonical entity UUIDs to satisfy today's mandatory
`subject_id`. An admin classification may remain descriptive metadata.

Use one controlled persistence/state path, including SQL/bulk producers; one
selection contract supplies headers, filtered rows, paging, CSV and resolution
workspaces. Preserve type-specific actions and server-side permissions. Finding
uniqueness must use the true stable condition scope; Computer-owned conditions
should not become new episodes merely because a client assignment changes.
Do not rewrite old episode identity without an audited conversion map.

Notifications and assessments currently include row kind in identity. Preserve
their continuity through explicit aliases/mapping; UUID retention alone is not
enough. Preserve historical version records and source-action target identity.
Candidates remain domain records participating through the common queue read
contract; this consolidation does not authorize candidate lifecycle repair.

## 5. One relationship mechanism, two meanings

Proposal: a narrow `finding_relationships` table containing tenant, upstream
finding FK, downstream finding FK, kind (`covers`/`requires`), rule/provenance,
scope evidence and validity/history. This supports multiple parents and chains
without a growing set of nullable parent columns.

- `covers`: the downstream condition is a symptom accounted for by the parent;
  hide its independent work row while the relation is valid.
- `requires`: an independent downstream problem has a specific prerequisite;
  retain its row with `First resolve: [issue]` and gate the relevant action.
  All applicable required prerequisites must be satisfied.

Extend/migrate existing type-level cover configuration into one documented rule
registry. A single controlled projector derives live relationships; retained
`finding_state.covered_by` arrays would be caches only. Enforce same-tenant
endpoints and no self-links with database constraints/composite tenant FKs;
the controlled writer must reject cycles with serialized/concurrency-safe graph
validation and deny bypass writes. Cover decisions require exact subject/scope
and evidence, not merely two types being active in the same tenant.

Pausing or filtering a parent does not satisfy a prerequisite. Closing a parent
triggers re-evaluation; it neither automatically resolves children nor bypasses
freshness guards. Preserve historical Admin/Jobs closures and reasons; do not
reopen them just because new handling retains related active findings.

## 6. Migration and cutover proposal

1. Complete a consumer/producer ledger: ORM and raw SQL, state functions and
   triggers, participants/assessments, notification identity, history, exports,
   actions, source targets, FKs, permissions/RLS and every `row_kind` reference.
   Known starting points include ingest evaluator/platform findings, identity
   client resolver, notifications, condition evidence, Operations condition
   readers/live projections, models, views, registry and SQL functions.
2. Expand the existing store and add mappings/relationship structures through
   new reviewed migrations. Keep old migrations immutable. Define common state
   authority, typed subjects and conversion rules before writing backfill SQL.
3. Rehearse conversion and reconciliation on an authorized isolated copy.
   Compare full populations, IDs, evidence, statuses, pauses, assessments,
   references and history; explain every semantic change. Avoid speculative
   deduplication during mechanical storage conversion.
4. Prefer a short coordinated writer-quiescence window and atomic final cutover
   if rehearsal proves feasible. Switch producers and readers together; avoid
   two independently authoritative ledgers. Exact locking, duration and rollback
   steps remain technical design work, not established facts.
5. Verify counts, direct links, history, permissions and action safety; retain
   legacy read/reference compatibility for an explicit rollback period. Once new
   writes occur, rollback needs a verified reverse map or a forward repair;
   restoring old readers alone is insufficient.
6. Retire the second ledger only after reconciliation and rollback criteria pass.
   Preserve retained history and legacy reference resolution. No conversion
   activates notifications or performs remediation.

Before execution, present exact affected files, migration SQL/data effects,
rehearsal evidence and recovery procedure for approval. This report specifies
the direction; it is not an executable or approved migration package. Record
the accepted durable architecture in an ADR before implementation closeout.

## Original PLAN-003 decisions and unfinished acceptance

| Original item | Current disposition / recommendation |
| --- | --- |
| W1 alert eligibility / D2 allowed types | Accepted: preserve the current 21 alertable types; new types default off, decisions/reviews do not alert, and severity alone does not confer eligibility. Review a named current/proposed/reason list alongside consolidation; do not accidentally inherit eligibility. Ongoing setting exists at Admin settings → Finding types (`/admin/finding-types/`), May alert. Delivery rules/guards remain separate; no new delivery authorized. |
| W2 counts and links | Home mapping contract accepted: Critical mapping issues (N) counts Critical findings across all applicable mapping types using queue eligibility. Open exactly those N with target groups expanded and results immediately visible, explicit Mapping · Critical · Open scope, plus View all mapping issues. One shared selection supplies count/destination. Remaining count/export implementation and acceptance are outstanding. |
| W3 decisions in queue | Existing software/capability handlers should be reused, with permissions and audit. Their presence does not prove all queue acceptance passed. |
| W4 / D1 offline threshold | Accepted: preserve configured shared offline policy and client/Computer overrides during redesign; use it consistently for applicable cover rules. Reviewed defaults are 7 days offline and a separate 30-day retirement-review signal, not effective settings for every client. Show relevant last-report time/threshold in evidence; silence alone does not prove retirement. |
| W5 relationship engine | Existing Computer cover and separate Admin/Jobs closure mechanisms need the unified contract proposed above. Pair-level suppression/severity contradictions remain open. |
| W6 withdrawn records | Superseded/moved to PLAN-004 and retired by migration 0316; do not reintroduce it in this queue redesign. |
| W7 Jobs chain | Exact-run upstream suppression exists but uses child closure. New retained relationships should be prospective; classify remaining unmet dependencies and preserve historical reasons. |
| W8 admin queue | Shared read-only projection exists but loses admin subject/client context and is used for counts. User-approved common-store scope supersedes retaining separate ledgers. |
| W9 housekeeping | Authorization gap, semantic duplicate audit and dormant-type classification remain; zero count is not retirement evidence. Hyper-V/VMware identity classification belongs with identity scope. |
| D3 vanished security-agent severity | Accepted: High for confirmed absence of a required security agent on a reporting Computer. Stale telemetry does not prove absence or protection loss. The proposed Critical branch was withdrawn: no supporting evidence contract or critical-risk policy was established. No new finding type; detector capability must be verified before implementation. |
| D4 phase order | Historical order was agreed. Expanded consolidation requires the revised staged cutover above, subject to review; do not represent it as executed. |

Original page acceptance still outstanding: all five categories and nonempty
types discoverable before pagination; complete cross-kind counts and exports;
independent group paging without 200-row auxiliary caps; correct critical
mapping deep links; paused/resolved and covered behavior; filter applicability;
permissions and audit; restored navigation; browser/mobile inspection; and
measured database/page latency. Historical targets were landing ≤1 s and
filtered ≤3 s; this review has not measured them.

## Review decisions and next action

### Accepted bulk-action direction

Accepted by the user: remediation/policy bulk actions require the same finding
type, not merely a common Category or taxonomy group. Pause/Resume may span
types where eligible; these change deferment, not the
underlying condition or policy decision. Current software prompts prohibit
generic pause/exclusion, so uniform pause is an explicit accepted design amendment,
not a claim of existing behavior. Resume also needs implementation verification.

Both visible-page and all-filtered-scope selection were proposed. At subgroup
level, all means that subgroup across pages, never the wider parent. Parent
selection must explicitly name parent scope/count. A mixed-type scope offers
only eligible Pause/Resume; type-specific actions require a homogeneous scope.
Keep controls in the active selection bar, show scope/count and clear selection
on scope changes. Server checks must repeat type, eligibility and permission
validation; same type alone is not sufficient.

Proposed available type-specific bulk actions reuse existing contracts:
bounded/deduplicated Refresh; reasoned Exclude for eligible types; software
approve/reject/investigate (publisher-wide effects explicit); remote-access
authorization with explicit client/all-client scope; capability confirm/reject;
identity merge/separate/split per independent case; client ownership move/keep/
source-wrong; lifecycle still-in-use/eligible retirement; exact-asset Hudu archive.
Source-group confirm/move/ignore stays in its existing mapping workspace.
Broader decision scopes must be disclosed, and all actions retain reasons,
audit and freshness/identity guards. Do not add generic Resolve/Acknowledge/
Delete or new universal remediation. User accepted the action set and mixed-type
Pause/Resume exception. Partial eligibility is now simplified and accepted:
use the action's normal confirmation, e.g. Archive 96 assets; 24 selected items
are ineligible. Keep server-side guards and a completed/skipped/failed result
summary with optional details. No separate preview page, extra eligible-subset
selection step or additional review workflow. Pause/Resume stays lightweight.
Implementation remains gated.

Root-issue lens accepted: queue work is one issue per proven underlying problem
and corrective action, not one issue per detector or one issue per Computer.
A source/job failure plus proven downstream fallout should present one repair
issue with impact, rather than necessarily create each consequence as another
finding. Preserve existing symptom history through covers; retain separate
symptom findings only when their lifecycle/history is needed. Requires retains
independent problems with separate repairs. Confirmed missing agent plus offline
remains two issues; the accepted missing-agent correction is unchanged. Unknown
cause warrants a scoped investigation, not a fabricated causal parent.
Existing cover pairs need classification as true symptom coverage, prerequisite
or assessment guard before conversion; do not retain blanket covers merely
because they are configured. In particular, offline must not cover confirmed
missing installation or automatically hide a known pending-reboot task.

Job-failure overlap accepted: timeout, scheduled failure and repeated failure
from the same proven failure episode/repair present one Job failure issue.
Retain timeout reason, attempts, schedule impact and downstream Jobs as evidence.
Separate scopes/repairs remain independent; Job name alone is not equivalence.
A successful retry resolves only after confirming the underlying condition
cleared, preserving attempt history. Next: source-connection versus collection
Job-failure overlap; identify the actual source/job scope and same causal failure.

Source/collection overlap accepted: one connection-failure issue when evidence
establishes the same source connection, cause and repair. Failed runs, stale
data and delayed downstream processing are impact. Independent processing
failures remain separate. Unknown cause is a scoped collection investigation,
not an inferred credential failure. Editing configuration alone does not prove
recovery; successful collection must confirm it. Next: Windows support-stage
findings, checked against ADR-0016/current projector. User accepted retaining
the existing alternative stages/types; verify transition/history behavior
rather than introduce a combined type. Next: F12/F13 software-risk evidence
versus the separate policy-approval decision. User accepted that boundary:
approval does not absorb/resolve independent software-risk findings. Next:
F14 patch-family review; ingest/patch_findings.py already makes never-patched
and stalled mutually exclusive, while repeated failure is per KB and approval
backlog is client-scoped. User accepted preserving those distinctions while
applying proven same-root coverage; no blanket patch-family consolidation.
Next: F07 unenrolled versus required-agent gaps, with detector evidence that
unenrolled means tracked by a non-agent source with no observed agent target,
not proof that a specific required agent is missing.

Next Jobs review evidence: current jobs_health_measurements_v1 (migration
0323) emits unmet dependencies only for blocked dependencies or waiting beyond
queue_registry.max_pending_age_m, not ordinary within-window waiting. Existing
platform findings suppress under an exact upstream failure using closure;
the accepted unified relationship direction will replace that split behavior.
Do not remove jobs_unmet_dependency wholesale or characterize every existing
row as routine waiting. Proposed boundary: preserve a breached dependency
finding when it needs an independent repair; otherwise relate to a proven
upstream cause, keeping its delay/impact visible. Exact classification and
repair ownership of the 244 measured active rows remain unverified.

Row interaction amendment accepted: no general finding-row expansion. Review
opens the evidence/history/comparison/related context in its owning workspace.
Retain the specific Related issues expansion for covers/requires. Merely
sharing a Computer is not such a relationship; do not add per-row related-CMDB
badges/count links or another grouping level for that context. The proposed
per-asset CMDB consolidation boundary has been discussed but not separately
accepted as a migration rule. F05 review clarified current versus proposed
grain: two configuration findings already aggregate; unknown lifecycle remains
Computer-specific. Blanket aggregation withdrawn because a common mapping fix
was not verified. User moved to the next case. Next: F03/F04 identity workflow
boundaries; PLAN-004 continues to own identity algorithms and repair.

Assessment clarification accepted in the subsequent review: an existing
job/source failure owns the repair and assessment impact. If a distinct
assessment finding exists and that failure accounts for it, use covers; if
the affected count is merely impact, keep it as parent metadata without a
synthetic child. A separate missing-data correction can remain independent,
with requires only where a proven prerequisite exists. Missing assessment
metadata alone is not an operator task. Readiness removal remains the stated
recommendation; the user moved to the next original decision after this
clarification without separately restating approval of every UI removal.

User review, 2026-10-27: accepted point 2 (covered visibility), point 4 (extend
the existing findings store), point 5 (one relationship mechanism with covers
and requires), and point 6 (staged migration/cutover direction). These are
design approvals, not authorization to execute migrations or implement the page.
Point 3 needs concrete definitions and context for each consolidation before
acceptance. The assessment handling clarification above resolves the latest
question about point 1. D3 severity direction is now accepted as recorded
above. Offline/agent rule accepted: agent-reporting loss can be covered by
Computer reporting loss where evidence supports that relationship; an already
confirmed missing required agent remains independent with unchanged severity;
unknown status does not establish absence. Patch/reboot rule accepted: remove
automatic patching-stalled cover of reboot-pending; retain both independently.
Use requires only when evidence establishes reboot as a prerequisite for
patching. Co-occurrence is insufficient; reassess after reboot rather than
automatically resolving patching. Software authorization review accepted:
review at the supported decision scope, with explicit client/broader scope,
affected clients/Computers and preserved exceptions. Distinguish rejected
installations from pending decisions. Popularity/publisher familiarity is not
authorization; approval clears only conditions explained by that decision,
not vulnerability or suspicious-installation findings. No bulk approval or
new decision scopes authorized. Type retirement accepted: zero active rows
alone does not justify retirement; verify replacement detection/actions/history,
and preserve intentional disabled status. Present a named retirement list.
For every open finding, either map to a verified replacement and close as
superseded with retained context/history, resolve on evidence of clearance,
close invalid detection with a documented reason, or retain it as open and
reviewable. No disappearance or resolution merely from migration. Preserve
pauses, decisions and audit history. Each retirement needs open counts,
disposition rules, replacement mapping and verification. Original D1 is now
accepted as recorded in its row above. D2 eligibility is also accepted with
the named consolidation-time review and existing admin configuration surface.
W2 home mapping count/label/destination contract is now accepted in its row
above. Count populations accepted: Open counts independent unpaused issues;
Paused counts independent deferred issues; covered symptoms appear only in
parent Related issues counts, outside independent-work totals. Requires links
retain both independent issues. Affected Computers is separate impact, never
added to issue counts. Headers, severity breakdowns, results and Issues CSV
share the full scoped population before paging. Preserve Open (18) · Paused
(3) presentation. Next: contextual definition of F09 software-review prompt
consolidation; no blanket approval of the proposed type merges. Subsequent
F09 challenge: merge recommendation withdrawn; the historical conversation,
implementing commit and later contrary grain change are recorded above.
Other pair-level corrections remain open.

Proceed through unresolved original decisions one at a time; do not bundle
them into blanket approval. Preserve unaffected accepted page decisions.
After design review, complete the consumer ledger and exact migration design.
Neither analysis nor this report establishes that the Issues page has been fixed.

Validation for this outcome is documentation/registry/governance validation,
recorded in BLUEPRINT. No application tests are warranted by these doc-only
changes. Existing governance debt: `docs/current-state.md` is older than 90 days.
VERSION and CHANGELOG remain unchanged because no release is being prepared.
