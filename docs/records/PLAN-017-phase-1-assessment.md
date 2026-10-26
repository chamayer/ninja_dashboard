# PLAN-017 — Phase 1 assessment

2026-10-25 author assessment; **Phase 1 accepted 2026-10-26** by independent
review ([Point 39, Claude round 20](../plans/review-plan-017-018.md#point-39--completed-author-assessment-after-abc)).
This completes the requested assessment synthesis from current local source,
Codex A/B1/B2 diagnostics and Claude's completed C measurements. Acceptance
does not complete PLAN-017, execute Phases 2–5, or authorize implementation.
Unknowns below are assessment dispositions with verification
owners, not implicit passes or requests for manual user measurements.

## Assessment conclusion

Keep the shared stable-record identity, canonical identity, evidence/history,
authored-state and effective-state boundaries while investigating their failure
contracts. The evidence supports targeted contract and publication work rather
than a platform rewrite or blanket removal of apparently duplicate stores.

The strongest outstanding concerns are acquisition completeness, cursor/demand
handoff, publication success versus asynchronous convergence, and the inputs
required for recovery after expiry. They have code-confirmed conditional paths,
not demonstrated platform-wide data loss. The new diagnostics found candidate
counts requiring interpretation; they did not establish contamination or make
every receipt-count difference an acquisition failure.

Serving cost is now measured for selected readers. Claude's post-0346 record
shows the observed 0345 Source-record regression improved, while the remaining
first-page query still takes about eight seconds. Small result pages and fast
count kernels do not bound the work of the full reader. Native/legacy storage
is substantial, but no measured copy is proven disposable or redundant.

Historical truth and recovery remain different from current-state convergence.
Latest raw payloads, material intervals and daily presence cannot by themselves
reproduce every receipt, previous raw body, past rule/reference version or
published answer. A retention horizon or destructive simplification cannot be
selected from these measurements alone.

## Evidence basis and reconciliation

The adopted [charter](../plans/PLAN-017-consolidated-data-architecture-review-draft.md)
defines A1–A10, S1–S14 and the phase boundaries. The original
[static assessment](PLAN-017-static-assessment.md), batches
[2](PLAN-017-static-assessment-batch-2.md)/[3](PLAN-017-static-assessment-batch-3.md),
[catalog/lifecycle record](PLAN-017-catalog-lifecycle.md), and
[gate ledger](PLAN-017-phase-1-gate.md) retain their detailed source traces,
inventory and all 29 materialized-view declaration destinations. This report
is the current synthesis; it supersedes their initial unexecuted/pending
descriptions without changing the original snapshots or review decisions.

Local HEAD at synthesis is `054dcfb`. The
[resume checkpoint](PLAN-017-gate-evidence/assessment-resume-checkpoint.json)
rechecked 951 snapshot-plus-delta source paths and the original six evidence
hashes. The only additional change among those pinned paths was the
Source-record identification test; new 0345/0346 migration hashes are retained
separately. Runtime source findings are grounded in the inspected code and
these content checks, not merely in dirty labels or commit times. No local
HEAD is treated as proof of production deployment.

| Evidence | What it establishes | Boundary |
| --- | --- | --- |
| [A/B results](PLAN-017-ab1-retry-results.md) and linked JSON | Named-role preflights, bounded installed metadata, plans, privileged aggregates and two size/statistics captures | D1/D2 index and constraint censuses hit row caps; base-table samples are prefixes, not random/global proofs |
| D1 at 22:48 UTC | 3,069 metadata rows including the later targeted index continuation; accessible Operations ledger then ended at 0344 | Ledger counts/names do not identify the application revision or prove all installed definitions match source |
| D2 at 22:48 and 23:04 UTC | 328 matched relation allocation observations; minimum capture separation 15m45s | Database reset timestamps were null; table reset epochs were not measured; cluster WAL is not dataset-attributable |
| B2 ending 23:05:40 UTC | Seven exact aggregate SELECTs completed under their read-only limits | This batch straddles the 23:05:29 deployment boundary reported by C; no single application revision is assigned to all diagnostics |
| D5.2/3 ending 23:19:04 UTC | Complete exact 30-day platform receipt aggregate and a pending-target snapshot | One explicitly disclosed small sequential-scan exception was used for D5.2; no window/LIMIT substitution |
| [Claude C record](PLAN-017-d4-results.md) | Runtime-role SQL, all 15 HTTP shapes, streaming CSV record counts, reconciled D4.5r and post-0346 measurements | Use its later deployment/re-measurement sections over stale opening text saying D4.5 was not run; no browser rendering or complete filter/content parity |

Claude records the 0345 container start at 23:05:29 UTC and 0346 at 23:33:31.
The earliest C HTTP window (22:46–22:48) may overlap initial Codex metadata work,
despite the scheduling confirmation that C was paused. Fine-grained overlap
and its load effect cannot be reconstructed from the retained aggregates. The
0345-era C work (R1 software, R2 Jobs, R3 Computers CSV, D4.5 timeout, D4.5r
at 24.3 seconds and the 29.6-second page) occurred between 23:05:29 and
23:33:31 without per-request timestamps. It may overlap the B2 tail through
23:05:40, D1 index continuation at 23:07:55, and D5 attempts at
23:12:49–23:14:40 and 23:18:57–23:19:04. Seconds for these C runs therefore
have a mixed-load caveat. Plan/work evidence (cost 1,704,944 to 196,684;
3.81 million to 335,000 shared hits; 16 loops and 595,008 lookups) still
supports the observed regression and improvement.
The post-0346 C measurements occurred after the last Codex probe at 23:19:04;
those later measurements do not overlap the recorded Codex probe window.
These are comparisons of existing records, not new external verification.

All C execution and its user-amended limits belong to Claude's record. No C
rerun, runtime repair or deployment was performed for this synthesis. Changes
and deployments reported by other sessions are preserved as separate evidence.

## Diagnostic interpretation

| Observation | Assessment | What it does not prove / next verification |
| --- | --- | --- |
| D3.1: 5,000 current keys, zero parity/multiple-open candidates | Positive evidence for the sampled current/open-history relationship | Does not prove all current/history rows, closed-interval nonoverlap or every writer |
| D3.2: 10 client-attribution candidates in 5,000; other queried missing/tenant/source counts zero | Observation client and canonical Computer client can differ; candidate scope needs an explicit semantic contract | One sampled tenant makes zero tenant mismatches non-discriminating; follow source mapping, attachment and moves under PLAN-004/015 |
| D3.3/4: zero queried missing catalog/daily-presence reference candidates in 5,000 each | Supports the sampled protected-reference paths | Does not establish all referential or expiry guarantees, or runtime-reader visibility |
| D3.5: 2,355 complete-count candidates in 5,000 | The equality predicate compares counts with different possible grains; treat as accounting candidates | Cannot label these 2,355 lost rows or failed complete snapshots without a same-grain accounting contract |
| D3.6 and D5.3: zero matching active Jobs/dirty work and zero pending software targets at their respective snapshots | No backlog observed by those exact snapshots | Not a continuous health/freshness guarantee; does not disprove U04 or show every publication stage completed |
| D3.7: 597 open recorded drift rows, below the 5,000-row cap and therefore the full open count at capture | Existing detector output is present; all were touched by one detector pass, with oldest `last_found_at` 23:01:19Z, about four minutes before capture | Last-found time says nothing about drift age or 597 freshly recomputed wrong verdicts; PLAN-014 owns policy/applicability verification |
| D5.2: 1,000 source receipts across six platforms; 39 failed, all Ninja; no successful-zero receipts | The exact uncapped 30-day predicate completed; failures warrant source/Jobs accounting review | No per-binding/root-cause attribution; no successful-zero observation in this window does not refute F01 |
| D5.1: 5,000 history keys, 266 open, 3,174 closed over 30 days, two over 90 | Describes an ordered history prefix and overlapping age bins | Not global proportions, a selected retention horizon or raw-fidelity coverage |
| D5.4/5: 558 capability-machine episodes, zero operator episodes in that relation snapshot; 68 column-statistic rows | Measures those relations/statistics only | Does not establish absence of authored state elsewhere or complete reference/payload width costs |

Receipt accounting has a concrete local explanation to test. The
[shared writer](../../ingest/source_observations.py#L249) starts with
`expected_rows=len(rows)`, then normalizes/filter rows and generates/coalesces
organization observations. The [Ninja writer](../../ingest/core/devices.py#L687)
starts with the device count but appends organization observations before
writing. [write_current_rows](../../ingest/observations.py#L452) returns accepted
upserts, excluding equal/older observations; it is not a received-row counter.
[complete_run](../../ingest/observation_runs.py#L106) derives complete/failed
status from explicit completeness and failed rows, not expected/written equality.
Thus the measured predicate is not currently a universal conservation law.
Which explanations account for the 2,355 production candidates is unresolved.
Proposed accounting separates fetched, rejected, deduplicated/stale, generated,
accepted and withdrawn identities before defining an invariant.

Client attribution also has a local competing explanation. The shared writer
selects a source-scoped/mapped client before falling back to a Computer's client;
[_attach_observation](../../ingest/identity/resolver.py#L299) updates device_id
without automatically replacing the observation's client. The current writer
preserves existing resolved IDs against null replacements. This is evidence
of distinct attachment/attribution inputs, not proof that the 10 candidates are
correct. A controlled move/remap example must state whether equality is required,
transitional or intentionally different before a repair is proposed.

### Storage and serving costs

First-capture relation totals include about 15.17 GB for
ninja_core.device_snapshots, 8.19 GB for
ninja_agent_compliance.platform_observations and 3.01 GB for
operations.entity_observation_current. Totals already include indexes/TOAST;
do not add them to their components again. Estimates/counters disagree on
some old relations, reinforcing the limit on population/churn inferences.
Over the short D2 interval, allocation increased for candidate events and
other change/publication stores; the 549,058,531 additional cluster WAL bytes
cannot be assigned to those relations or used as a sustained ingest rate.
The interval mixed ordinary workload and diagnostic reads.

Claude's runtime measurements distinguish small kernels from full readers:

| Measured shape | Recorded result | Assessment consequence |
| --- | --- | --- |
| Computer count / Source-record count / type choices | About 8.7 / 61.9 / 93.4 ms execution in the initial version | These are individual kernels, not full-page SQL decompositions |
| Computers HTML | About 6.3–8.8 s across measured variants/repetitions | User-visible request cost exists even with a cheap population count; other SQL/Python/template costs are not separated |
| Source-record D4.5r after 0345 | 24.326 s execution; 3.81M shared hits; observation branch 16 loops and three config lookups 595,008 loops each | Confirms substantial repeated work in that captured plan; buffer hits are accesses, not distinct pages |
| Source-record D4.5r after 0346 | 7.994 s; 335,277 shared hits; plan total about 196,684 | Observed regression improved after joining configuration once; does not prove all remaining cost is one cause |
| Source-record HTML after 0346 | 7.4–9.1 s, one sample per shape | Similar range to the pre-0345 samples; no statistical claim of exact equivalence |
| Source-record CSV after 0346 | 14.767 s, 37,188 complete records | Count matches the earlier measured source population, not proof of identical rows or filter/masking parity |
| Computers CSV | 12.936 s, 5,508 complete records | Count matches the measured current Computer population at that capture |
| Software HTML | About 21.5 s on the successful re-measurement | Remaining dominant measured request; decomposition is unknown |

The original 15-second D4.5 timeout is superseded by the later reconciled,
authorized D4.5r measurements; it is not an unfinished measurement task.
The local [0346 definition](../../operations/apps/core/migrations/0346_restricted_layouts_join_once.py)
corroborates moving configuration work out of the per-row scalar form. Its
comment's narrow JIT explanation does not quantify the whole 24.3-to-8.0-second
change; TIMING FALSE node counts cannot assign per-node elapsed costs.
Repeated observation scanning/cardinality error and final sorting remain
leads, not authorization for a new index or removal of the metadata boundary.

C used an application admin identity with operations_app database connections.
That does not establish ordinary-user or per-client scope parity. HTTP timing
is direct CLI transfer/first-byte time without the proxy/browser path. CSV
parser counts handle quoted newlines; table-row counts and equal population
counts are not full content, card/filter, privacy or browser-render validation.

## U02 — Optional site acquisition and absence authority

**Static disposition complete: code-confirmed conditional gap; deployed impact
unverified.** Finding **F08** accepted in the independent Phase 1 review. Criteria
A2/A3, scenarios S3/S4/S6; conditional severity Medium for missing/withdrawn
container evidence, incidence unknown, high confidence in the inspected path.

[SentinelOne _fetch_sites](../../ingest/connectors/sentinelone.py#L72) deliberately
catches an exception and returns collected site rows so agents can continue.
That best-effort availability choice is reasonable. However, fetch merges the
partial site list into one ordinary list; the shared writer derives completeness
only from the source's is_partial_snapshot flag, not this failed site substream.
With any other accepted row and a source not marked partial, it completes the
source-wide snapshot and
[reconciles absence](../../ingest/observation_runs.py#L146). An older active site
with no agents and omitted by the failed fetch can be withdrawn along with its
open history interval. Agent-derived groups can protect sites present through
agents. A wholly empty merged list instead follows F01's early-return path.
No inspected live source marks this snapshot partial. The run is still recorded
as successful, so the failed site fetch is visible only in an application log;
run receipts cannot count its incidence. A later successful fetch restores the
site as a new active episode, while the false closed history interval remains.

The consequence has a current consumer: the
[client resolver](../../ingest/identity/client_resolver.py#L87) selects active,
unattached org observations. A wrongly withdrawn empty site no longer enters
that input. This does not prove deletion of canonical clients, withdrawal of
agent-derived groups or a production incident.

Options are to carry independent completeness by namespace/substream, retain
site absence state when the optional fetch fails, or explicitly make sites
additive best-effort evidence with a distinct withdrawal authority. None is
selected or implemented here. PLAN-017 R02 coordinates PLAN-002/007; the first
verification is a bounded synthetic complete-agent/partial-sites example with
a previously empty site and a later successful retry. No vendor/API call or
database experiment is required to grade this conditional code path; those
tests remain gated. U02 is no longer an untraced static lead.

## U04 — Coalesced demand and consumer acknowledgment

**Static disposition complete: a specified concurrency candidate, not a
demonstrated lost update.** A1/A4/A10, S8/S9/S10; possible stale-publication
impact Medium, runtime likelihood and global serialization unknown.

[Inventory producers](../../ingest/inventory/software.py#L490) insert one pending
title/key/source using ON CONFLICT DO NOTHING in the mutation transaction.
The [intel matcher](../../ingest/intel/matcher.py#L468) also produces targets;
its conflict path updates `queued_at` on an existing pending row.
[pending_scope](../../ingest/software_reconcile.py#L1256) reads IDs and scope in
a transaction that ends before reconciliation. The
[consumer](../../ingest/operator_job_queue.py#L1080) reconciles/publishes, then
consumes IDs in another transaction. The consumption predicate has no captured
generation/revision test. Pending uniqueness prevents duplicate pending keys;
it does not itself fence producer work arriving during consumption.

The candidate interleaving is: consumer captures target T and evaluates input
generation G; producer commits a new change for T after that relevant read,
coalescing into the same pending row; consumer then acknowledges T by ID.
Whether a successor or another pass sees the new input is not established by
the acknowledgment predicate. Existing zero-pending snapshots cannot rule out
that interleaving. The possible loss is reclassification demand, not inventory
data.

The [registry](../../shared/jobs_registry.py#L961) separates software-inventory
resources from software-state/software-findings, consistent with
[0262](../../operations/apps/core/migrations/0262_jobs_software_writer_capacity.py).
This removes the claim that these named resources necessarily serialize the
two domains; it does not prove actual overlap or exclude other serialization.
Whole-fleet/no-target reconciliation is real recovery coverage, and publication
failure before consumption leaves demand pending. The consumer declares a full
fleet run daily and after every decision; if that schedule runs successfully,
it limits staleness to one full-fleet interval. Preserve these mitigations
without treating the installed schedule or recovery interval as verified.

Options for later comparison are generation-aware acknowledgment, a durable
post-consumption recheck, or a demonstrated common serialization contract.
Do not disable intentional domain concurrency merely because keys differ.
R06/R01 and PLAN-002/005/007/software owners should first inspect current
workflow/supersession rules and reuse target-scope tests, then run a disposable
two-connection barrier test across read/mutation/acknowledgment for both
inventory and intel-matcher producers. No installed
lost-update frequency, permanent loss or recovery-time guarantee is asserted.

## Findings disposition and proposed direction

Existing detailed findings retain their original evidence and accepted review
boundaries. Deployment incidence remains unverified unless stated otherwise.

| ID | Current assessment / confidence | Conditional impact | Disposition and proposed owner |
| --- | --- | --- | --- |
| F01 | Code-confirmed complete-empty early return; UI receipt consumer is distinct from evaluator Jobs guard | High if authoritative empty input leaves stale active evidence; no observed zero-success example in D5.2 | Keep as finding; define complete/partial/ambiguous-empty envelopes with PLAN-002/007 |
| F02 | Code-confirmed cap/frontier skip path under backlog beyond cap | High conditional acquisition gap; occurrence unknown | Keep; compare bounded catch-up/per-stream frontier under PLAN-002/007 |
| F03 | Code-confirmed cursor-before-durable-demand window; generic events/full checks mitigate | Medium conditional software freshness gap | Keep stage-specific; compare atomic demand/cursor or tested retained-event recovery with PLAN-002/005/007 |
| F04 | Code-confirmed publication contract versus swallowed/non-complete stages; previous-state cache inputs remain relevant | High conditional stale authoritative fields | PLAN-012 item 4 retains ownership; choose explicit synchronous or observable asynchronous contract after mechanism checks |
| F05a | Code-confirmed unbatched observation/software purge transaction; no measured contention attribution | Medium conditional maintenance load | Later bounded deletion/cutoff/reference comparison under R08; no maintenance performed |
| F05b | Code-confirmed per-batch claim purge with no total job bound | Low conditional maintenance occupation | Assess bounded continuation against workload; do not confuse with F05a's transaction span |
| F06 | Code-confirmed committed-inventory versus publication-retry window; classifier repairs some stages | Medium conditional stale readers; no permanent-loss claim | Keep stage-specific title/safety/catalog/exposure acknowledgment map; software/Jobs owners, not automatic reopening of completed PLAN-011 |
| F07 | Accepted local clean-rebuild contract mismatch: preserved reference identity/authorship are extra inputs | Medium if destructive recovery relies on the wording | Preserve anchors/authored state and distinguish in-place repair from clean reconstruction; R06/R08 |
| F08 / U02 | Accepted conditional partial-site absence path; deployed incidence unverified | Medium conditional org-evidence error | Namespace completeness/absence authority, R02 and PLAN-002/007 |
| U04 | Unfenced coalescing/acknowledgment pattern; complete runtime concurrency contract unverified | Medium possible stale publication | Retain as targeted verification candidate, not a proven incident or accepted fix |
| Measured reader cost | Runtime observations in C; 0345 regression improved by independently implemented 0346 | Measured seconds of latency; no invented service-level violation | PLAN-012 owns further serving cost; retain original masking/scope contract and current metadata view boundary |

Recommended order is to establish completeness/accounting and publication
contracts before optimizing away evidence or copies; test recovery/acknowledgment
boundaries before claiming rebuildability; then compare physical designs using
end-to-end costs and compatibility. Keep source-native facts, material history,
daily presence, effective values and typed/native read models where their grains
and guarantees differ. A cheaper replacement must supply parity, generations,
rollback limits and retained identity/authorship before retirement is proposed.
No architecture/retention decision is adopted here; future accepted decisions
require their normal ADR and implementation scope.

## A1–A10 disposition

These are architecture acceptance criteria, not a score for whether the review
was written. No platform-wide criterion is proven satisfied by prefix samples.

| Criterion | Assessment result | Required next evidence |
| --- | --- | --- |
| A1 Authority | Conditional publication/acknowledgment gaps F04/U04; shared identity and effective-state authorities traced | Stage/generation success contract and writer/decision invalidation checks |
| A2 Acquisition | Conditional violations F01–F03/F08; accounting grains differ | Complete/partial/empty/cap/rejection tests and explicit conservation accounting |
| A3 Lifecycle | Shared withdrawal/history and canonical preservation mechanisms; F01/F08 and move semantics limit guarantees | Reappearance/remap/merge/split examples with retained evidence and action provenance |
| A4 Rebuild/correction | Not established; F04/F06/F07 and previous-selected/authored inputs matter | Disposable current-repair, clean recovery and corrected replay with sources unavailable |
| A5 Historical truth | Not established; material intervals/daily presence are not full raw or rule history | Define published-at-T versus corrected-at-T inputs/horizons; cost their retention |
| A6 Safe expiry/replay | Not established; closed-interval guards and RESTRICT references are positive mechanisms | Cutoff baseline/reference/undo/replay coverage during concurrent reads and collection |
| A7 Capacity | Selected sizes, short allocation interval and reader cost observed; sustainable rates unestablished | Writer/API/stage/refresh/catch-up rates, longer reset-aware growth, total I/O and capacity assumptions |
| A8 Transition | No replacement selected or adopted; owner boundaries retained | Candidate-specific parity, identity/authorship preservation, publication order and rollback gates |
| A9 Scope | Named-role preflights passed and sampled tenant/reference results are consistent; tenant checks are non-discriminating with one sampled tenant; ten attribution candidates need semantics | Scoped move/reassignment examples and runtime ordinary-user/filter/export checks |
| A10 Necessary work | Distinct store purposes traced; repeated reader work measured; full writer/refresh cost unknown | Compare kept copies/full passes against correctness, recovery and measured total work |

## Scenario and path coverage closure

The static-authoring exit condition is a review destination and explicit
disposition for every discovered path, not an assertion that every implementation
line, live dependency or scenario was experimentally verified. The original
947 routed files and corrected forward-definition/ORM/matview inventories remain
the discovery basis; new source migrations are recorded as deltas, not silently
folded into immutable counts.

| Scenario | Static assessment disposition / next verification |
| --- | --- |
| S1 | New client/Computer order traced in batch 2; anchor creation precedes identity use but does not prove first-pass effective/cache publication. R03/R04, PLAN-004/012 |
| S2 | Mapping/client attribution and stable source identities have separate roles; rename/remap/reuse behavior needs controlled examples. R02/R03, PLAN-004/015 |
| S3 | F01/F02/F08 and differing receipt grains establish conditional completeness risks; malformed/permission-limited source incidence remains unknown. R02/R07 |
| S4 | Successful complete absence differs from silence/failure; shared withdrawal preserves canonical identity, F01/F08 constrain absence. R02/R04 |
| S5 | Merge/split/membership/action history is not arbitrary historical rollback; dirty identity work remains owned by PLAN-004/015. R03/R08/R09 |
| S6 | Hudu archived/relayed evidence is not contact authority; namespace/parent keys and container-only sites have explicit roles. Missing-parent/VM-only fixture outcomes remain R02/R03, not a blanket identity defect |
| S7 | Strictly newer observation guard and receipt/contact distinctions traced; counts can legitimately skip stale writes. Clock-skew/late correction behavior remains R02/R08 |
| S8 | F02/F03/F04/F06/U04 identify boundaries; shared current/history transaction is positive evidence. Identical retry and A→B→A after expiry remain R01/R04/R08 |
| S9 | Identity/snapshot locks and pending uniqueness traced; they are different contracts from U04 acknowledgment. Manual/collector overlap and supersession remain R01/R03/R06 |
| S10 | Required publication is not implied by acquisition success or zero pending at one instant. F03/F04/F06 and Jobs/output trace retain R01/R04/R06 verification |
| S11 | Decision-trigger/config/time mechanisms traced in batch 3; source equality alone cannot drive all invalidation. R04/R05/R06 |
| S12 | Privileged integrity samples and runtime positive reads are distinct; attribution and negative scope cases remain R03/R05/R09/R11 |
| S13 | Backlog cap, bounded drain and measured reader costs observed; sustained catch-up and mixed workload capacity remain R01/R02/R07 |
| S14 | Dataset-specific reference/expiry/recovery needs traced; no universal time/last-N policy selected. Concurrent disposal, cutoff and offboarding remain R08/R09 |

| Path | Completed assessment basis | Remaining bounded destination |
| --- | --- | --- |
| R01 Jobs/services | Entry/packaging routes, terminal output and resource boundaries; B2 snapshot | Phase 2 failure/retry/supersession mechanisms; no schedule/queue manipulation |
| R02 acquisition | Five fetcher contracts, shared/Ninja accounting and U02/F08 | Synthetic completeness/normalization/partial-namespace fixtures |
| R03 identity | Stable/source versus canonical grain, first identity, attribution and current owner work | Controlled move/undo/reappearance checks with PLAN-004/015 |
| R04 projections | Authority/typed-cache fallback, invalidation and publication order | PLAN-012 item 4 mechanism tests and explicit success/generation proposal |
| R05 policy/findings | Stored verdict/operator-state boundary; 597 existing drift records | PLAN-014 policy verification and event/dedup/history checks |
| R06 software/reference | Per-device completeness, stage-specific F06, U04, authored/global references | Two-connection ack/retry and clean-rebuild experiments preserving identity |
| R07 native/legacy | Native readers/refresh declarations, F02/F03 and storage evidence | Dynamic/external consumer closure before any retirement; PLAN-006 stays deferred |
| R08 lifecycle | Dataset retention matrix and F05/F07, sampled ages/episodes | Cutoff/reference/replay/undo tests and count/time/hybrid alternatives |
| R09 schema | Forward SQL/ORM/generated definitions plus capped installed metadata; 0345/0346 delta | Narrow catalog-definition continuations where a decision depends on omitted metadata |
| R10 tests | Existing synthetic/testcontainer and unit fixture mechanisms inspected | Reuse 8–12 shared-contract checks after local experiment authorization |
| R11 readers | C complete for its approved shapes, latest D4.5r and version windows | Ordinary-user/filter/content parity and remaining stage decomposition only when justified/authorized |

Every original materialized-view declaration lead retains its chain/destination
in the gate ledger. Direct dependency metadata does not close ordinary-view,
function/dynamic or external consumer edges. Those are explicit R07/R09/R11
verification boundaries; none justifies deleting a compatibility object.

## Continuation, effort and acceptance boundary

The Phase 1 authoring work is complete with these graded unknowns and routes.
Independent review accepted the Phase 1 gate in Point 39, Claude round 20;
N1–N6 are non-blocking wording corrections. No ROUND_COMPLETE marker or
successful diagnostic batch substitutes for that acceptance. PLAN-017 stays
active, Completed remains —.

The retained planning range for Phases 2–5 is **7–16 engineer-days**, excluding
setup/approval delays and any requested Phase 1 amendments: Phase 2 2–4,
remaining measurements 1–3, targeted verification 2–5, design/triage 2–4.
Completed A/B/C should not be rerun wholesale; remaining measurement effort
covers the unmeasured writer/refresh/retention/catch-up and scope questions.
This remains a planning estimate, not elapsed-work arithmetic or authorization.
Narrow it when a separately authorized later phase selects the high-impact checks.

First compare bounded complete/partial/empty publication, cursor handoff,
same-title mutation during acknowledgment, first-identity publication and
catalog/expiry reconstruction using inspected disposable fixtures. Then collect
only missing costs needed to compare 2–3 candidate contracts/designs. Final
target design, retention/recovery tradeoffs and transition plan belong to their
later gates. No new business-duration question is needed to deliver this
assessment; the withdrawn day-only question stays withdrawn.

Deferred verification is routed in the root backlog by this report and its
R-paths. PLAN-002/005 remain verify scopes; PLAN-004/012/014/015/007 retain their
existing implementation ownership; PLAN-006 stays deferred and PLAN-008/011
stay completed. No reopening, implementation or new standing check is adopted.

No application code, dependency, public interface, ADR, release version or
runtime file changes are needed for this assessment. Local validation covers
registry routing, Markdown links/whitespace, source/evidence digests and scope
of the documentation edits. No production probe, test database, experiment,
maintenance, repair, migration, deployment, commit or push was performed for
this synthesis. A later phase starts only after separate authorization from the
verified root checkpoint.

## Closing validation

Passed: the 18-entry registry validator; scoped git diff whitespace check;
951 snapshot-plus-delta source hashes; 0345/0346 hashes; original six evidence
hashes; unchanged A/B and latest C input records and local HEAD; all 10 criteria,
14 scenarios and 11 path IDs; 91 local Markdown file links and whitespace.
No runtime source was edited and no application/database test or external
probe was run for this assessment. This is document/source corroboration,
not an additional claim of production behavior.

Repository-wide diff check retains an unrelated Operations blueprint EOF blank
line at 751. Root BLUEPRINT.md still exceeds its existing 4,000-byte governance
cap. Those issues were not repaired. The older root TODO label calling
PLAN-007 deferred conflicts with its active registry entry; implementation
routing here follows the registry, and no unrelated status was silently changed.
