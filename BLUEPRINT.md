# PLAN-017 — Consolidated data architecture review and target design

## Status and goal

2026-10-25: user adopted the independently reviewed consolidated charter;
PLAN-017 is active and PLAN-018 superseded with source provenance preserved.
Phase 1 static work and the exact A/B1/C diagnostic scopes are authorized by
the user. Subsequent Point 38 assigns C to Claude in a new session using
reviewed metrics-only commands; its command-review/confirmation boundary applies.
B2 was subsequently explicitly approved for the seven exact D3 SELECTs and
completed. Runtime remediation, broader phases, commits and pushes remain gated.
Goal: assess authority, acquisition/publication, lifecycle/recovery, efficiency,
scope, and physical design against A1–A10; propose justified future changes.

## Scope and steps

Documentation/evidence only: charter status, registry routing, this checkpoint,
and `docs/records/PLAN-017-static-assessment.md` with linked static inventories.
Pin HEAD and dirty-source digests; enumerate entrypoints/objects; trace shared
contracts and exceptions; map lifecycle, readers, scenarios, constraints/tests;
record findings/unknowns, later-phase effort, and bounded diagnostic proposals.
Preserve source plans and existing runtime/other-plan work. PLAN-012/014 and
identity/Jobs owners retain implementation authority; this assessment observes
their scopes and rechecks changed boundaries rather than competing with them.

## Decisions and checkpoint

Review checkpoint (2026-10-26): **Phase 1 accepted by independent review**
(Point 39, Claude round 20) on assessment sha256 983872ba…f94f at HEAD 054dcfb;
digests and the 949-path baseline deltas reverified. No acceptance blocker.
Six Low non-blocking corrections N1–N6 (0345-era C/Codex overlap, intel-matcher
producer, single-tenant A9 wording, F08 log-only detection/self-correction,
TODO pass/fail wording, D3.7 detector-pass reading) are applied or verified;
none changes findings, routes or the 7–16
engineer-day later-phase range. F08 Medium conditional and U04 candidate
dispositions are confirmed. PLAN-017 stays active; Completed remains —.
Documentation only: no probes, experiments, runtime changes, commits or pushes.
The original accepted assessment bytes/hash are preserved in the gate-evidence
snapshot (983872ba…f94f); the amended assessment hash is d2d7a465…4cdf.
`docs/records/PLAN-017-gate-evidence/assessment-wording-corrections-checkpoint.json`
records both hashes and unchanged A/B/C digests. Possible 0345-era probe
overlap qualifies C seconds; plan/work evidence still supports regression and
improvement. A concurrent PLAN-004/015 identity/Operations commit advanced HEAD
to 7a0e791 after review; the 949-file baseline now has eight changed paths
(three previously known and five additional), recorded with digests in the
correction checkpoint. Review that delta before a later phase; it does not
retroactively change the accepted 054dcfb assessment. Validation: registry 18
and governance passed (existing blueprint-size
and current-state-date warnings); 25 assessment links and scoped whitespace
checks passed. Next action: await separate Phase 2 authorization, review the
concurrent source delta, and define pass/fail criteria at entry. No manual user
measurements assigned.

Current diagnostic checkpoint (2026-10-25): **Part A bounded query set is
complete**, including all D5.2/3 SELECTs. Initial transport failures/holds and
all original evidence are preserved in linked records. Corrected P0 passed
operations_migrate, PostgreSQL 16.14, read-only, tenant 1, pg_catalog,
superuser/BYPASSRLS. D1 plus reviewed targeted index continuation captured
3,069 metadata rows; both D2 snapshots captured 15m45s apart; all D5 captured.
D1/D2 global index/constraint coverage remains capped/incomplete. No global
integrity, retention, bloat, capacity-rate or Phase 1 completion is inferred.

User directed "finish part A" after the pending exact two-SELECT/scan-exception
request. Final one-batch D5.2 small sequential-scan exception recorded; no SQL,
planner settings, schema or runtime configuration changed. Final D5.2/3 batch
passed in 3.750 client seconds with five-second statement caps. D5.2 exact
uncapped 30-day platform-only aggregate: 1,000 receipts across six platforms,
39 failed receipts (all Ninja), zero successful-zero-row receipts; no kind/
source_key values returned. D5.3 zero pending at its snapshot. Not cause or
continuous-health evidence. No A query remains skipped on unmet index metadata.

B1 seven plain plans/costs/rows reported; subsequent explicit user approval
covered all seven B2 SELECTs, all passed in 12.063 client seconds. D3.6 current
valid status-index path reviewed against obsolete index dropped by local 0223;
exact query unchanged. B2 candidates: 10 client attribution, 2,355 complete-count
receipts, 597 existing drift records; assessment needed, no defect/repair claim.
Results: `docs/records/PLAN-017-ab1-retry-results.md`. Safe JSON/SQL evidence in
PLAN-017-gate-evidence, final `part-a-completion-checkpoint.json`.

Concurrent source delta preserved: three reader/template/test changes and local
0345; latest local HEAD fcb488a from other work. Original six evidence hashes
match; no source deltas beyond recorded checkpoint. A/B1 SQL and D2 wrapper/P0
were unchanged; no production state inferred from local files. This session
created no runtime changes, migrations, maintenance, repairs, deployments,
commits or pushes. Preserve all other work and Claude's C section below.

Codex probe window released; no Codex probe active. C belongs to Claude, not
executed here; its separate checkpoint now reports C work/no active probe.
Probe overlap/deployment consistency not verified here; keep that limitation.
The consolidated assessment above now supplies aggregate interpretation,
completed U02/U04 static dispositions and latest C version/timing reconciliation.
Next is independent whole-gate review; no C measurement task remains. No manual user measurements. PLAN-017 and Phase 1
remain open; no further production tests or later phases inferred from finish A.
Local closing checks passed: registry (18), scoped diff, evidence JSON/links/
whitespace, transport syntax, original hashes/source-delta reconciliation and
final SELECT role/read-only/budget checks. Global diff retains unrelated
Operations EOF whitespace at 748; root blueprint exceeds its existing size cap.

C checkpoint (Claude, 2026-10-25): user-approved metrics-only C commands ran
(SSH to Docker host; SQL via app container as operations_app; HTTP from host
python3 to loopback Gunicorn as app `admin`). D4.1–D4.4c passed; all 15 HTTP
shapes measured under user-revised limits (HTML 90 s, CSV 120 s, 20 min, one
re-measure after confirmed completion). D4.5 (D1.11 waived): plan cost
1,200,867; gate overridden; ANALYZE hit 15 s timeout, not retried. Deploy of
`fcb488a`/0345 confirmed at 23:05:29Z (container start): first SQL/HTTP runs
pre-deploy, later runs post-deploy. D4.5r (adds `observation.restricted`,
TIMING FALSE, 28 s): 24.3 s execution, 3.8M buffer hits; observations scanned
16x (instances est 1/actual 16) and three per-row evaluator_config lookups ran
595,008x each. Post-deploy `/inventory/source-records/` re-measured: 29.6 s
(pre-deploy 6.6–8.5 s), a confirmed regression across the 0345 deploy.
After `ee180e1`/0346 deployed (23:33:31Z): Source-record HTML 7.4–9.1 s, CSV
14.8 s / 37,188 records, D4.5r 8.0 s (cost 196,684); regression resolved.
Overlap with Codex probes unchecked. Results: `docs/records/PLAN-017-d4-results.md`.
Next action: none for C; measurement is complete. No C probe active.

Previous stopped-attempt checkpoint (historical):

Resume A/B1 checkpoint (2026-10-25): user reconfirmed exact A/B1 approval;
B2 remains unapproved and C belongs to Claude. Verified HEAD 70e64f5, all 951
snapshot-plus-delta source paths, five checkpoint paths, four reader-function
digests and original six evidence hashes; no staged changes. Existing work
is preserved. Source verification evidence:
`docs/records/PLAN-017-gate-evidence/resume-ab1-source-checkpoint.json`.

User reserved A/B1 and confirmed Claude C paused. Initial helper/P0 attempt
returned exit 2 with no validated role/version/read-only result. Raw output
suppressed; cause unknown. Stopped without retry or fallback. No numbered
D1/D2/D3/D5 body, D3 SELECT or EXPLAIN submitted; no plan costs/rows exist.
Results: `docs/records/PLAN-017-ab1-results.md`; safe execution metadata:
`docs/records/PLAN-017-gate-evidence/resume-ab1-execution.json`.
Codex probe window released; no Codex probe remains active. C retains its own
Claude review/confirmation gate; no manual measurements assigned to the user.

Local dummy test confirmed embedded SQL quotes are stripped/split by the
PowerShell 5.1 native invocation; likely transport cause, not a production
diagnosis. Encoded SQL stdin shape passed both local native-boundary tests;
shared helper unchanged and no production retry. Evidence in A/B1 results.
Next action: review corrected exact P0 invocation, fresh source recheck and
new coordinated window before explicitly resuming stopped A/B1 batches. Existing A/B1
authorization persists; do not request it again. Request B2 only after actual
B1 costs/rows and risk review. Phase 1/static coverage/U02/U04 remain open.
Local registry (18 entries), scoped diff/whitespace and evidence JSON checks
passed. Global diff retains Operations blueprint EOF blank line at 735; root
blueprint still exceeds its 4,000-byte governance cap. No runtime changes,
maintenance, migrations, repairs, deployments, commits or pushes authorized.

Prior handoff (retained for context):

Checkpoint after Claude round 19 / Codex round 17 (2026-10-25): C assigned to
Claude in a new session using minimal metrics-only commands. Do not assign C
to the user as a manual browser task; H2 human procedure superseded/retained
as history. No general executor requested. C commands/output reviewed and
confirmed before production use per Point 38; missing helper runtime-role or
authenticated HTTP path stops C, no session/privilege fallback.
A/B1 remain Codex's scope and retain earlier explicit "all approved" approval.
Round 19's "not approved by this direction" adds no approval; it does not revoke
that prior user authorization. Do not request A/B1 approval again. B2 separate.
No diagnostic execution by this session. F07 accepted, U02/U04/static closure
remain separately routed; whole-gate completion is not inferred.

H1: D5.2 is an uncapped aggregate over tenant-1 source.* receipts within 30 days,
grouped only by split_part(kind, '.', 2); never return full customer-bearing kind.
Existing index eligibility and plain-plan gate remain; 5-second statement and
30-second batch limits bound execution. Timeout gives no complete counts; no
silent window change/retry. Other sampled datasets retain their 5,000-key caps.

C safety/measurement contracts remain: operations_app, operations,public
wrapper, 15 GET shapes/19 max requests, no client bindings, approved caps and
Computers CSV last under numeric gate. No body/CSV/customer IDs/auth/private
URL/raw error in agent-visible output. Streaming CSV parser handles quoted
newlines; transfer-only sinks cannot establish row counts/parity. Metrics-only
results go to docs/records/PLAN-017-d4-results.md after execution. CLI timing is
not browser rendering; report method/cache differences and unknown metrics.

Request scope in `docs/records/PLAN-017-approval-request-draft.md`: A D1/D2/D5 as
operations_migrate, B1 D3 plain plans as that privileged role, C D4 operations_app
SQL plus HTTP now owned by Claude in a new session (Point 38). A/B1 approval
from "all approved" persists; the C handoff itself grants no A/B1/B2 authority.
H3: ask B2 separately only after B1, quoting actual startup/total plan costs and
estimated rows (plus expensive-node/access-path details); no invented numbers.
Planner costs are not milliseconds. B1 authorizes no D3 SELECT execution.

Original/fresh evidence and previous deltas retained. Latest verified concurrent
HEAD 70e64f5; sources named by round-15-checkpoint.json unchanged against that
recheck, original six hashes match. No installed/deployed state inferred.
Large CSV evidence remains a later commit-time exclusion candidate; retain now.
Later-phase effort remains 7–16 engineer-days plus Phase 1 amendments/setup delays.

Validation: closing local checks/limitations in gate record. Known unrelated
Operations EOF blank line and root blueprint size cap remain outside scope.
Execution split: Codex owns A/B1; new Claude session owns all C SQL/HTTP.
Run production probes sequentially and coordinate scheduling to avoid overlap.
Next: fresh sessions recheck HEAD/digests and approved dependencies; Codex
executes approved A/B1; Claude follows Point 38 command review/confirmation.
Quote actual B1 costs/row estimates before requesting B2. Fresh session strongly
recommended before the next independent outcome; no C manual task for user.

# PLAN-012 — Computers inventory read model

## Goal

Make the Computers inventory page fast without weakening its full-fleet
contract. Preserve canonical computer data, tenant isolation, coverage
verdicts, source and Hudu state, filters, summary cards, CSV, and
current-versus-withdrawn semantics. Reusable fleet facts move into an owned,
rebuildable read model refreshed after ingest.

## Scope

One rebuildable effective read model owned by the existing source, identity,
coverage, and Hudu authorities, with a refresh function integrated into
`refresh_derived()`. No cache or duplicate authority. Requirement-rule
changes are out of scope; they belong to PLAN-014 (`ingest/BLUEPRINT.md`).

## Status

Active. The read model itself has not started.

Done under this plan (pushed to both remotes):
- `cc5d936`: the evaluator stores requirement verdicts (ADR-0035, migration
  0332). This prerequisite gives the read model one requirement authority.
- `453c41c` and `ccae6da`: Computers page fixes the user requested (card
  order, one Hudu card, Status filter over every catalogued agent, one-line
  filter bar, compact cards, clearer Hudu column, OS "Unknown"). These are
  page fixes, not read-model progress.

Not done:
- no inventory read model or materialized view;
- no refresh function and no `refresh_derived()` integration;
- the route still assembles fleet state from several runtime queries;
- no performance re-measurement, parity validation, release documentation,
  or plan completion.

## Evidence

Deployed 0.128.15 measured Computers at 4.740 s browser first response: 3.154 s
of database wait across 15 fleet reads, plus 1.209 s of template rendering.
That was before `cc5d936`, which replaced the page's requirement derivation
with one indexed read. Re-measure before designing.

Production after the first verdict pass (2026-10-21 17:48 UTC): 19,012
verdicts. Hudu Missing went from 4,208 on the page to 260. The drift check
shows 582 open findings with no matching verdict, which the resolve step's
separate rule copy explains (PLAN-014).

## Validation

Recorded with each commit: migration 0332 and evaluator Postgres tests,
Computers page tests (20), Edge screenshots, and the full suites. Each run
had only the 8 failures that also fail on HEAD 3091a47.

## Checkpoint

Prerequisites and page fixes are deployed. The read-model design has not
started.

## Next action

Re-measure the deployed Computers page. Trace each remaining runtime query
to its authority. Define the read model, its refresh owner and
`refresh_derived()` hook, its tenant boundary, staleness behavior, and
parity checks before implementation. Then move the Dashboard and
software-capability requirement copies to the stored verdicts.
