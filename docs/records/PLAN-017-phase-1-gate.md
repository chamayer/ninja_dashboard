# PLAN-017 — Phase 1 gate candidate and closure ledger

Review outcome (2026-10-26): **Phase 1 accepted** by independent review in
debate Point 39 (Claude round 20), with six Low non-blocking corrections N1–N6
recorded there. The pending-review wording below is superseded. Acceptance
does not complete PLAN-017 or authorize Phases 2–5. N1–N4/N6 are now applied
to the consolidated assessment; N5 was applied to the root TODO during review.
The reviewed assessment bytes remain in the gate-evidence snapshot, and the
original completion checkpoint remains historical evidence. The
[wording-correction checkpoint](PLAN-017-gate-evidence/assessment-wording-corrections-checkpoint.json)
records both assessment digests and unchanged A/B/C input digests.
A separate identity/Operations commit advanced HEAD to 7a0e791 after review;
its current source deltas are recorded in that checkpoint for a later-phase
recheck. It does not retroactively change the accepted review baseline.

Current status (2026-10-25): **Phase 1 author assessment complete; independent
review and gate acceptance pending.** The
[consolidated assessment](PLAN-017-phase-1-assessment.md) is the current synthesis.
A/B1/subsequently approved B2 are complete; Claude completed C, including
reconciled D4.5r and post-0346 measurements. No further C work or manual user
measurements are assigned. Diagnostic completion alone does not close Phase 1.
U02 now has a code-confirmed conditional finding (F08, review pending); U04 has
a specified interleaving/mitigation/verification disposition, not a proven
incident. All R01–R11 and A1–A10/S1–S14 paths have dispositions and next gates.
Measurements retain cap, scope, cache, version-window and early-overlap limits.
Fresh-session independent review decides acceptance or exact static amendments;
no Phase 2–5 execution, remediation, deployment, commit or push is inferred.

Earlier gate-candidate checkpoints below are retained as provenance; their
pending/unexecuted descriptions are superseded by the current synthesis.

2026-10-25. **Prepared for independent static review; not accepted and not
marked complete.** Production access, runtime changes and Phases 2–5 execution
remain unauthorized. A/B1/C diagnostic approval is now requested separately
as specified below; no permission is inferred pending the user's selection.

The [assessment](PLAN-017-static-assessment.md), batches
[2](PLAN-017-static-assessment-batch-2.md)/[3](PLAN-017-static-assessment-batch-3.md),
[catalog/lifecycle checkpoint](PLAN-017-catalog-lifecycle.md), corrected
[fresh inventory](PLAN-017-gate-evidence/source-baseline.json) and
[exact D1–D5 drafts](PLAN-017-diagnostic-queries.md) form this packet.
Original six-file evidence and source plans are preserved.

Round 19 / Point 38 supersedes C's human assignment: Claude owns C SQL/HTTP
in a new session using reviewed minimal metrics-only commands. The H2 human
procedure is retained as superseded history, not a user task. Numeric gates,
roles/caps and privacy remain; command review/confirmation precedes production
use. A/B1 retain prior "all approved" authority; B2 still separate. This session
performed only documentation updates, not diagnostics. Earlier checkpoints below
retain historical descriptions and do not override this assignment.

Round 18 update: G1–G5 confirmed. H1 changes D5.2 to an uncapped 30-day
tenant/source aggregate grouped only by platform, never full customer-bearing
kind. H2 adds the [private human procedure/metrics table](PLAN-017-D4-human-measurement.md),
including cache-disabled DevTools, CSV record counting then deletion and a
numeric Computers CSV gate. The [approval request](PLAN-017-approval-request-draft.md)
is issued for independent A/B1/C choices; approval remains pending. B2 will be
requested separately quoting actual B1 plan costs/row estimates, not guesses.
No production access occurred. Whole static-gate acceptance remains separate.

Earlier round 17 checkpoint (superseded for request readiness):

Round 17 update: F07 accepted. G1–G3 diagnostic amendments and recommended
G4/G5 are applied in the query document: separate application-path D4 wrapper;
no D4.S/client-filter probes; proposed human-only private HTTP executor/session
protocol; direct partial-index pending-state samples and recent run receipts;
Computers CSV last; independent A/B/C approval scopes. The
[approval wording](PLAN-017-approval-request-draft.md) is a draft for user review,
not a request for access. Amended execution/privacy details still require
independent review. Claude explicitly did not review every static ledger row;
whole-gate acceptance is not inferred from this round.

Latest local [recheck](PLAN-017-gate-evidence/round-15-checkpoint.json) records
HEAD 70e64f5 from concurrent work and the same four reviewed reader-function
digests as the previous delta; three changed/two added source paths remain
relative to the immutable fresh snapshot. It supersedes only the closing
checkpoint below, not either snapshot. No assessment commit was made.

Concurrent-source checkpoint: after the fresh snapshot, `views.py` and
`source_records.html` and `test_table_controls.py` changed, and migration 0344 plus
`test_source_records_identification.py` were added by concurrent work. Their
digests and reviewed reader-function digests are preserved in the separate
[delta](PLAN-017-gate-evidence/checkpoint-delta.json), without rewriting either
snapshot. These paths route to R09/R10/R11. D4.5 is updated to the new local
Source-record row query; D1.11 checks required metadata columns. Issue-count
enrichment is covered by the full-request probe, not its row-query timing.
Concurrent commit a3fb9df includes these five paths; later dirty reader/template
changes remain. This assessment created no commit. Migration 0344 is not asserted deployed and no migration/release is authorized.
Current-reader cardinality/scope and compatibility are assessment/owner review
work, not approval of that concurrent implementation.

## Gate criteria and status

| Phase 1 deliverable | Confirmed state | Limit / gate disposition |
| --- | --- | --- |
| Baseline | Snapshot HEAD 0c812db, closing HEAD a3fb9df from concurrent work; original and fresh snapshots preserved; fresh copy includes catalog; later reader/migration changes recorded in delta | A source baseline is not a deployed version/catalog. Recheck snapshot-plus-delta before resuming/execution. |
| Discovery destinations | 947 routed source/packaging files; 329 Django and 115 ingest migration files; 112 ORM mappings; corrected lexical name count 506 | Lexical/model counts are leads. Imported/dynamic SQL, installed kinds and external consumers have explicit R09/D1 destinations. |
| Authorities/publication | Shared observation/identity/claim/effective/cache, verdict/finding and native/software/Jobs traces recorded | F01/F02/F03/F04/F06 conditional gaps; generations, retries and invalidation are not globally verified. |
| Lifecycle/recovery | Dataset classes, material/raw/receipt distinction, protected references, global catalog, authorship and previous-state inputs mapped | F05a/F05b/F07 and U04; no duration, version count or clean-rebuild guarantee selected. |
| Scenarios/criteria | A1–A10 and S1–S14 explicitly accounted for as local mechanisms, conditional findings or unresolved work | No platform-wide criterion passes from static work. Remaining verification is assigned below rather than treated as silently passing. |
| Constraints/tests | Explicit ORM and SQL unique/check/FK/privilege/trigger examples; relevant existing test fixtures inspected | Full installed constraint parity and every writer/role are not verified. Phase 2 uses inspected disposable fixtures only after authorization. |
| Assessment/options/effort | Consolidated author assessment complete; F01–F07 retained, proposed F08/U02 and U04 dispositions, measured candidates/costs, alternatives and owner routes recorded | Independent acceptance pending; incidence and unmeasured costs remain explicit. Retained later-phase planning range 7–16 engineer-days. |
| Diagnostics | A/B1 and explicitly approved B2 captured; Claude C complete including reconciled D4.5r/post-0346 reader shapes | Capped metadata/prefix samples, mixed version windows and possible earliest plus 0345-era C/Codex overlap; seconds from potentially overlapping runs have a mixed-load caveat while plan/work evidence supports the regression and improvement. Post-0346 C followed the last Codex probe. No global scope/content-parity/capacity proof. |

This packet advances the gate from a shape-only diagnostic proposal to a
concrete review draft. It does not establish that every implementation detail
or all materialized-view transitive dependencies have been proved. The reviewer
must decide whether the remaining static unknowns have sufficient destinations
or need more Phase 1 tracing before this gate can close. Do not equate a
ROUND_COMPLETE marker or lack of comments with gate acceptance.

## Path and unknown closure ledger

| Destination | Local result / unknown and impact | Owner / next verification | Dependent gate |
| --- | --- | --- | --- |
| R01 entrypoints/Jobs | Child/workflow/fenced output sequence traced; receipt need not prove inner completeness. Installed definition/recovery/supersession races unknown | PLAN-017 assessment; coordinate PLAN-002/005/007. D1 signatures/dependencies, then Phase 2 failure/claim/replay checks and any required definition inspection | No global success/freshness claim before stage/terminal contract is resolved. |
| R02 acquisition | Five _FETCHERS audited; complete-empty and cap/hand-off findings. U02 partial-sites absence path traced through shared reconciliation and active-org resolver (proposed F08); deployed incidence remains unknown | R02 + PLAN-002/007; inspect vendor/fixture evidence, Phase 2 complete/partial/empty examples, D3 receipt candidates | No withdrawal fix, source API experiment or claim of source completeness from a successful request alone. |
| R03 identity/actions | Inline anchors, mappings/moves, merge/split provenance, first-client/Computer order traced; ongoing dirty identity work preserved | Coordinate PLAN-004/015; bounded new-identity/move/undo tests, inspect latest inverse-action/FK references | No identity/data repair or clean replay that discards learned/authored state. |
| R04 projections/policy | Claim signature vs effective dirty queue, explicit 0313 invalidation, retired hostname rationale and read-time/time-driven effects traced. F04 and previous-state clean-rebuild inputs unresolved | PLAN-012 item 4 retains implementation ownership; Phase 2 stage failure/policy/retained-selection checks; D1 current function/trigger parity | Decide synchronous contract versus explicit asynchronous publication before changing failure semantics. |
| R05 findings/requirements/notifications | Stored verdict authority, condition policy/freshness, operator state and notification record boundaries mapped; domain transaction/duplicate-event completeness unresolved | PLAN-014 owns applicability; R05 Phase 2 representative finding/decision/retry checks and latest read-view trace | Do not claim evaluator output freely rebuildable or exactly-once notification events; delivery reliability stays excluded. |
| R06 software/global references | Full/partial list guards, persistent targets, stage-specific F06 mitigation, catalog identities, dedicated assertion authority and F07 mapped; U04 read/mutation/ack interleaving and whole-fleet recovery specified | R06/R08 and Jobs owners; inspect supersession/resource edges, synthetic interleaving/rebuild; D1–D5 scope includes catalog | No clean catalog rebuild/retirement or reliable-publication claim from material-change flags alone. |
| R07 native/legacy domains | Native patch/activity/health readers and refresh declarations remain; L10 cap path confirmed. External compatibility and all transitive matview readers unknown | R07/R09/D1; Phase 2 cursor/catch-up, then measured readers/refreshes | Preserve deferred PLAN-006 and native source-domain functions; no unused-store conclusion from Python search. |
| R08 retention/disposal | Closed-interval guards, daily/run references, authored/operator classes and batch-vs-job costs traced; full cutoff/reference/concurrency/history coverage unknown | R08; Phase 2 bounded expiry/reappearance/rebuild/undo; D2/D5 measured size/growth and Phase 5 count/time/hybrid alternatives | No disposal, retention-horizon selection, rollback or raw-history guarantee without evidence. |
| R09 schema/index/view/trigger | Both migration paths and ORM mapped; 075 nullable-key repair, imported/generated definitions and catalog omission reconciled as leads; all installed/transitive definitions remain unknown | R09/D1; compare exact installed definitions where signature alone is insufficient, retain metadata limits | No global object-count, index-retirement, bloat or role-scope conclusion from lexical evidence. |
| R10 tests | Shared observation/history/run fixtures and capability/condition/software/identity/Jobs test leads recorded; none run during static work | Reuse existing tests; inspect fixture isolation and choose 8–12 shared-contract checks for Phase 2 | Local experiment authorization first; no production/test-env credential substitution. |
| R11 readers/admin/exports | Source-health UI consumers, separate Computer/source-record grains, safe metadata boundary and export helper traced; complete filter/card/CSV timing/scope parity unknown | PLAN-012 readers, PLAN-014 verdicts; D4 exact scoped requests plus runtime-role probes after review/authorization | A privileged query, first page or capped export cannot prove full runtime-reader parity. |

U02 static assessment is complete: SentinelOne optional-site exceptions can
feed a source-wide complete snapshot and withdraw an omitted empty-site org
record; the active-org resolver is an affected consumer. F08 is proposed for
independent review; no deployed incident or canonical-client deletion is
asserted. U03 remains locally reconciled with live/external consumer limits.
U04 static disposition is complete as an unfenced coalescing/acknowledgment
candidate with explicit recovery mitigations; actual overlap/lost update and
its freshness bound need a later bounded experiment. See the consolidated
assessment for sources, competing explanations, options and owners. These are
assessed verification gaps, not silently passed guarantees or approved fixes.

## Materialized-view declaration routing

Every one of the 29 original distinct materialized-view CREATE-name leads has
a destination below. Inputs are local declared dependency leads, not a current
live dependency closure. A dynamic definition or ordinary-view intermediary
must remain unresolved until expanded; an empty lexical input list is not
evidence of no dependencies.

| CREATE-name lead(s) | Input/refresh or retirement chain | Remaining verification |
| --- | --- | --- |
| ninja_core.latest_device_health | SQL 073 reads operations.ninja_device_health_current_shadow; device-health refresh | Expand shadow-view dependencies and installed freshness/generation. |
| ninja_core.v_active_devices | SQL 073 reads Ninja devices/custom fields/policies and generic detail shadow | Native domain purpose/joins still matter; full downstream audit R07/D1. |
| ninja_core.device_troubleshooting_signal | SQL 073 recreates from a captured installed view definition, not a new literal body | Dynamic stored pg_get_viewdef dependency is explicit; D1/live definition is required before graph closure. |
| ninja_activities.device_activity_signal | SQL 017 reads activities; dynamic refresh list in activities ingest | Cursor/publication ordering F02/F03; direct/transitive readers R07/D1. |
| ninja_activities.patch_warning_events_recent; system_reboot_events_recent | SQL 068 activities rollups, same three-view refresh transaction | Native patch/Computer signal consumers and cost remain unmeasured. |
| ninja_patches.current_patch_state; latest_install_outcome; device_patch_signal; device_patch_activity | SQL 016/070 patch_facts and aggregates; explicit patch refresh order | Expand all intermediate relations and parity to source facts; measure only when authorized. |
| ninja_inventory.source_observations_current; unresolved_source_records_current; devices_current; serial_quality_current; identity_conflicts_current; merge_candidates_current; inventory_summary_current | SQL 063 wraps corresponding *_live views and rewires public views to materialized current copies; refresh function orders seven | Ordinary *_live definitions and compatibility readers are R07/R09/D1, not assumed retired or redundant. |
| operations.agent_presence_current | Historical name renamed in 0047 | Historical alias lead, not a separate current-store count. |
| operations.device_agent_presence_current | 0077/0098 generic current observations + devices | Snapshot/typed/matview scope and generations D1/Phase 2; health namespace excluded by 0098. |
| operations.device_session_current | 0134 f-string body: presence and generic Ninja reboot/current evidence, then Windows servicing/effective readers | Expand f-string and latest view dependencies explicitly; no literal-only parser equivalence claim. |
| operations.device_patching_scope_current | 0121: devices/source links, Ninja policies/custom fields, patching defaults/allowlist | Mixed generic/native scope authority; R07/R09/D1. |
| operations.client_health_trend_current | 0049 clients/findings | Time bins and recomputation/cleanup consumers; R05/R07/D1. |
| operations.source_health_current | 0077 via 0098: current observations, presence and source.* run-log latest/success | F01 UI false-healthy path; separate from evaluator's Jobs/output guard; current installed definition D1. |
| operations.software_title_current; v_software_safety | 0293 title from installations; safety from title, decisions, aliases, CVE matches/signals and intel.cves | F06 two committed refreshes and classifier mitigation; all dependency generations/read costs R06/D1/D4. |
| operations.device_software_exposure_current | SQL 114: installations/history/readiness, findings/condition policy, source metadata/lifecycle, catalog products/versions | Live approval/freshness boundary and classifier consumption; R06/D1/D4. |
| operations.v_device_software_exposure_base; v_client_software_issue_rollup | Created in 083, explicitly dropped as matviews by 084 | Retired physical-kind leads in local forward chain; do not count alongside replacement views as active copies. Verify installed kinds D1. |
| operations.v_eol_mapping_candidates | Created in 081, explicitly dropped as matview by 088 | Same historical-kind distinction; current mapping/reader path R06/D1. |

The 0061 coordinator orders presence → session → patch scope → client trend →
source health; separate collection projectors and software/native refreshes are
outside that one function. Concurrent refresh does not prove a single coherent
generation. D1.6 is a direct relation-edge measurement proposal, not a complete
function/dynamic/external consumer graph.

## Findings/options and acceptance disposition

F01–F04, F05a/F05b and F06 retain their graded claims/alternatives and original
implementation ownership. F01 now explicitly includes the operator-facing
false-healthy path requested in round 16, grade local-only. F07 adds a local
catalog clean-rebuild contract contradiction, accepted by Claude round 17.
No data-loss/contamination incident is established. Selected runtime reader
costs are measured in Claude C, including the improved post-0346 regression;
incidence of the conditional correctness findings remains unknown.

A1/A2/A3 have sampled preventive mechanisms and conditional gaps; A4/A5/A6
retain explicit fidelity, identity, authored state and cutoff/replay requirements;
A7 has selected size/reader observations but lacks sustainable writer/refresh rates; A8 has no selected replacement; A9 has local
scope mechanisms but no full installed/runtime-role audit; A10 requires total
cost evidence before simplifying copies or full passes. All remain unknown at
platform scope. The assessment's S1–S14 table still governs scenario routing.

The old day-only question remains withdrawn. Phase 5 must present recovery and
history coverage as costed count/time/hybrid alternatives. No business question
or authorization is needed to finish this static review candidate.

## Effort and review request

The original 10–22 engineer-day estimate included 3–6 days of remaining Phase 1
and 7–16 for Phases 2–5 (2–4 local mechanisms, 1–3 measurement, 2–5 targeted
verification, 2–4 design/triage). The later-phase range remains **7–16 engineer-
days**, excluding approval delays/setup, conditional on shared-contract reuse
and reviewer acceptance of the remaining coverage limits. It is not a promised
duration or approved continuation. Any further Phase 1 tracing is additional
and must be re-estimated from review findings; no elapsed work is inferred from
turn count or timestamps. Show the accepted estimate before proposing Phase 2.

Claude's next review is concrete: review the remaining static
coverage/dependency destinations and G1–G3 amendments to exact D1–D5 SQL/roles/HTTP/export
limits and role feasibility; decide whether this is sufficient Phase 1 coverage
or identify required static amendments. Only explicit review acceptance can
close this candidate gate. No production or Phase 2 approval is requested here.

## Validation

Round 18/H1/H2 local checks passed: registry (18), scoped diff, Markdown file
links/whitespace, nine structural SQL blocks, uncapped platform-only D5.2 shape,
all 15 matching query/procedure/table routes, embedded CSV-count Python AST,
current HEAD/source and original evidence hashes. Global diff check retains
the unrelated Operations EOF blank line at 735. No DB parser/plan, DevTools,
CSV execution/deletion, session/login or production validation was performed.
The H2 procedure has static checks only; actual plan costs do not exist yet.

Round 17 amendment checks passed: 18-entry registry, scoped diff check,
Markdown file links/whitespace, nine SQL structural blocks, 15 measured GET
shapes with no client binding and Computers CSV last, current HEAD/source
digests and original six-file evidence hashes. Structural SQL checks are not
PostgreSQL parsing or plan review. Global diff check still reports the unrelated
Operations blueprint EOF blank line at 735. No live/local DB, HTTP, credentials,
role configuration, CSV handling or privacy execution was exercised. The
human/private-browser protocol is proposed wording, not a tested executor.

Earlier gate-candidate capture checks:

Passed: 18-entry registry validation, scoped diff check, local Markdown file
links/whitespace, builder AST/JSON checks, catalog-only copied-builder diff,
and all six original evidence hashes. Eight SQL blocks passed structural
quote/parenthesis checks only; PostgreSQL parsing/planning remains unvalidated.
Fresh-builder check returns nonzero for the recorded HEAD change and three
changed/two added source paths; snapshot-plus-delta is the closing basis, not
a claim of an unchanged worktree. No application tests, request timings,
physical costs or installed-role/catalog behavior validated. Global diff check
reports unrelated operations/BLUEPRINT.md EOF whitespace at line 735; root
blueprint exceeds the existing governance size limit. Neither is repaired here.

## Assessment completion validation and independent review

The current consolidated author assessment integrates all approved diagnostics,
latest C measurements, current-source digests, U02/U04 and every criterion,
scenario and review destination. Original inventories/records remain intact.
No new production probes, runtime changes, database tests, experiments,
migrations, deployments, commits or pushes were performed for this synthesis.
Local checks and remaining repository-wide documentation limitations are recorded
in the assessment closing checkpoint. Independent review must assess coverage,
F08 grading, U04 disposition, accounting/scope interpretations and evidence
limits before accepting Phase 1. A fresh session is recommended for that review.
