# PLAN-056 — Coverage reader remediation

## Active resume checkpoint — 2026-11-17

Commit authorized by the user's `commit + push` instruction. This is an
incomplete, disabled candidate, so VERSION/CHANGELOG remain at 0.144.28 under
the no-version-bump-for-incomplete-work rule. Push remains gated on explicit
inclusion of reviewed migration 0422 and its automatic deployment. The migration
adds four tenant-isolated tables, indexes, eleven statement invalidation
triggers and protected refresh/publication functions; renamed presence/session
refresh functions receive invalidating wrappers. Jobs admission starts after
the schema exists even when the reader flag is off. Thus disabled rendering
does not make a push operationally inert. PostgreSQL lifecycle/access/concurrency
validation and the known filter edge below remain open. Commit scoped runtime
candidate and handoff/evidence only; exclude local `.work` prototypes and
unrelated untracked recovery scripts. No separate redeploy.

Latest resumed validation: default/combined/text HTML matched after CSRF masking;
all captured context fields equal. Multi-batch CSV (client population selected
between 101 and 250 Computers) matched exact response bytes. All returned 200.
Final optimized baseline/candidate seconds: default 5.455/1.624; combined
5.418/1.055; text 6.447/1.007; CSV 8.068/0.757. Temporary publication preparation
3.551 s is excluded. Earlier unoptimized default samples 4.334/1.063 and
6.467/2.227 demonstrate variability, not a guaranteed sub-two-second page.
Next persistent schema/access/concurrency/maintenance and remaining filter edges.

User requested reducing the remaining .227 s. Bounded cProfile attribution found
selected-page observation details consuming .462 s of a 1.948 s profiled request.
Changed only the candidate adapter's protected source-link join: correlate the
lookup to selected withdrawn observations with LATERAL/OFFSET 0. Current
observations never consume missing_since in these aggregates; duplicate link
rows do not change bool_or/max. Follow-up profile measured .036 s for that SQL
and 1.437 s full request, with exact HTML/context parity. Different snapshots and
host load mean the .425 s SQL reduction is sampled, not a controlled benchmark.
The unprofiled four-scenario comparison above validates the final adapter. No
index, persistent schema or server-setting change was needed for this repair.

Fixed text selection's correlated materialized-text scan by joining its unique
per-Computer result once. Aligned HTML search text with the legacy omission of
withdrawal ages before presentation. Final comparison used one repeatable-read
runtime-role snapshot, session-local tables and a fixed transaction/as-of clock
for readiness and Python ages; real expiry was not certified. Signed-cookie
authentication excludes deployed database-session cost. Candidate second;
browser/network and cold state excluded. Twelve-second SQL/110-second process
limits. Rollback/connection close and exact host/container cleanup confirmed.
No persistent migration, source/queue/session data change or serving hotpatch.

Local syntax, Django base system check, focused module lint/format and registry
checks pass. Full views lint retains complexity and magic-number findings,
including extracted normalization complexity. Local Docker did not respond and
was stopped; no local database work ran. Persistent migration/rollback, RLS,
writer/access, concurrency, upstream readiness and refresh/expiry remain open.
CSV combined with withdrawal-age text search remains a known uncertified edge:
legacy CSV includes those ages but the SQL text selector omits them. Full filter
matrix and empty/missing-publication paths remain unverified. Deployment remains
gated on migration-inclusive approval. docs/operations.md's separate-redeploy text
conflicts with AGENTS.md's no-separate-redeploy instruction; no release attempted.

## Prior implementation scope and evidence

Resume reconciliation: current Git diffs contain a newer disabled
`COVERAGE_MAINTAINED_READER` path in views/middleware, metadata and selected-ID
hydration, Sources text selection and batched CSV. This work is ahead of the
recorded four-input adapter measurement and has no certified full-response
result. Preserve existing work and validate that candidate first. Review local
0422/maintenance/access before any cutover; no commit/push/production migration
authorization is inferred from resuming. No local fleet or timing run.

Implementation resumed on explicit user instruction: replace fleet preparation
with maintained selection plus selected-ID hydration, preserving the existing
normalizer and presentation helpers. Include metadata/cards, text filters and
batched CSV. Validate complete candidate responses and maintenance/access before
cutover; no commit/push/deployment approval. Blueprint remains Operations-owned.

Latest full-response measurement: 3.309 seconds candidate versus 4.144 seconds
baseline; complete HTML identical after masking CSRF. Four prepared input queries
replace source reads in the standalone adapter; original Hudu reader retained to
preserve record ordering. Two-second target NOT met. No serving cutover or
persistent migration. Next remove remaining full-fleet request preparation and
resolve Hudu ordering, then validate persistent maintenance/access before release.

Current checkpoint: measured maintained-reader regression repaired with a
reader-scoped JIT setting. Default/combined selector 0.728/0.515 seconds with ten
fields matching the direct selector. Next validate persistent schema, maintenance
and access, then finish text/detail/export integration and full-page parity/timing.
No persistent migration or serving cutover has occurred.

## Complete Django response measurement

User authorized measuring the full page. Added isolated coverage_page_reads.py
compatibility adapter and extended the unexecuted 0422 publication with contact/
observation facts, evaluation timestamps and Hudu observation metadata required
by the existing renderer. It is not imported by serving views. Source contact,
requirements, Computer and observation inputs come from prepared facts; existing
client/agent rosters, source-record counts, Hudu inventory and bounded detail
readers, Python page assembly and actual templates remain in the request.
This adapter does not add the separate 0.728-second selector to the request: it
feeds maintained inputs through the current view's selection/assembly instead.

First five-input adapter runs returned different HTML. Context comparison found
corrupted em-dash text in the prototype's not-applied statuses (39 visible Cleanup
cells in that snapshot) and reordered Hudu records on two visible Computers.
Corrected the status literals in both selector and frozen publication SQL. Kept
the original protected Hudu reader in the measured candidate, preserving its
current display order; the maintained Hudu adapter remains uncertified/unused.
Earlier count/ID parity did not certify these display labels or record order.

Final same-snapshot default-page comparison: baseline 4.144 seconds; candidate
3.309 seconds, about 20% faster, with full byte-for-byte HTML equality after
masking only the CSRF form token. Both returned 200. Includes full Django test
client middleware, authenticated user lookup, view, real detail queries, context
processors and rendering. Signed-cookie authentication was used for both to avoid
writing live sessions; deployed database-session backend cost, browser/network
and cold-cache certification are excluded. Candidate ran second in the same
process. JIT was disabled/restored around only the four prepared input SELECTs;
all other SQL retained the original setting. Temporary publication preparation
took 3.072 seconds and is excluded from response latency as background work.

Diagnostic used runtime-role protected reads, one repeatable-read snapshot and
session-local tables (including the candidate FK/column layout), with twelve-
second statement/eighty-five-second process limits. No persistent migration,
trigger, queue, session or source data changed. Transaction rolled back,
connection closed, temporary tables discarded and exact staging cleanup verified.
The two-second full-page target remains unmet; persistent RLS, refresh lifecycle,
concurrency, failure/expiry handling and filtered/export full-response parity
remain unverified. Local syntax, focused Ruff/format, Django system, registry and
whitespace checks pass. Candidate is uncommitted, unconnected and undeployed.

User now authorizes building the maintained read model, including scoped schema
and Jobs maintenance, within five minutes. Implement locally; do not migrate or
deploy production. Serving cutover requires initialization, maintenance and
parity evidence. This supersedes the earlier no-schema implementation scope.

Five-minute outcome: migration 0422, ingest/coverage_read_model.py, Jobs registry/
handler/admission wiring and coverage_selection.maintained_selection implemented
locally. Contract: operations/docs/decisions/0059-coverage-maintained-selection.md.
Python compilation, focused reader/producer Ruff, Django system check, registry
and whitespace checks pass. PostgreSQL migration/rollback, writer permissions,
refresh-wrapper behavior, concurrency, complete parity and speed are unverified.
Candidate is not serving or deployed. Next validate schema and maintenance on a
small synthetic PostgreSQL fixture; inspect shared revision-row contention and
upstream publication readiness before initializing or cutting over. Existing
Sources text/detail/CSV integration gaps remain. No test files were added.

Quick measurement authorized by the user: one standalone remote diagnostic used
session-local pg_temp tables, the existing runtime role and a repeatable-read
snapshot. No persistent migration, hooks or data writes were applied. The exact
frozen publication input query populated temporary Computer/cell tables with
the candidate's primary/selection indexes and ANALYZE. Population took 2.929 s;
current selector 2.594 s; maintained selector 7.583 s. All ten returned fields
matched (aggregate arrays compared without incidental JSON aggregate ordering).
This is one default-filter selector comparison, not full-page timing, cold-cache
certification, or validation of the persistent schema/RLS/maintenance lifecycle.
The maintained implementation regresses and must not be activated. Next inspect
its actual plan and eliminate the measured reader regression before integration.
Ten-second statement and seventy-five-second process bounds applied. Transaction
rolled back, connection closed and temporary tables discarded. Exact host and
container staging cleanup verified. No customer values or source identifiers
were emitted or copied to the workstation.

Immediate regression repair: one bounded actual plan on equivalent temporary
facts measured 7.204 seconds, including 6.638 seconds of JIT compilation across
235 functions. The planner estimated 2,636,515 filtered rows versus 5,733 actual;
compilation dominates this measured regression. The maintained reader now turns
JIT off only around its SELECT, restores the previous setting on success, and
rolls back the atomic block/settings on error. No server or serving-file setting
changed. Underlying JSON/materialization cardinality estimates remain a design
limitation; this change does not claim to correct those estimates.

One follow-up repeatable-read comparison on session-local indexed/analyzed facts:
default direct selector 3.570 seconds versus maintained 0.728; combined reporting
scopes/Ninja Missing/any-platform Online/last-page direct 2.901 versus maintained
0.515. All ten result fields matched in both, with the same aggregate ordering
normalization as above. Temporary-fact population and full page are excluded from
these selector times. This confirms the immediate reader regression is repaired,
not persistent-schema/RLS/maintenance or two-second full-request acceptance.
The twelve-second statement/eighty-second process bounds, runtime role, protected
source snapshot and output restrictions remained. Transaction rolled back and
connection closed; exact host/container staging removal verified. Ruff lint/
format, Python compilation and Django base system checks pass. No tests added,
commit, push or deployment. Next persistent migration/access/concurrency and
maintenance validation before page integration and full output/latency evidence.

Reconciled against HEAD 7e8e44e5 and the worktree: serving views/readers have
no substantive diff; the isolated selector and unrelated recovery scripts are
untracked. Global state, any/no-platform and Computer-scope selection,
requirement-card aggregates and Django-compatible page clamping are now in
the isolated selector. Default and one combined-filter read-only comparison
passed; selector alone remains about 2.6 seconds. Next complete Sources text
semantics, then bounded detail/export integration and full output parity.
Keep the selector isolated until those gates and full-request timing pass.
No new tests, schema, commit, push or deployment in this continuation.

## Goal and scope

Reduce complete Coverage request cost without losing data or weakening
[R1–R9](../decisions/0006-platform-read-contract.md). User requests an effective
fix after .28's parity-preserving presence semijoin showed no HTTP improvement.
No new dependency, public interface, schema or architecture without approval.
Commit/push/deployment remain separately gated.

## Confirmed state and decisions

.28 / 7e8e44e5 is deployed. Last HTML sample 4.424 s; no speedup established.
Earlier traces measured distributed SQL and fleet preparation but did not fully
attribute fetch/template/framework time. Do not assume another small SQL tweak
solves the page. Keep all output fields, populations, filters, ordering and CSV.
Do not add a page cache or move unbounded detail behind a final LIMIT.

## Steps and validation

1. Attribute remaining full handler cost, including fetch and rendering.
2. Implement the demonstrated improvement in existing readers/views/templates.
3. Verify full output/context parity under a consistent snapshot, plus meaningful
   selected-filter/page/export checks. Temporary read-only diagnostics may run
   in standalone processes; never replace serving files or write live data.
4. Measure candidate before proposing release. Keep limits and uncertainty
   explicit. No full-fleet workstation processing or new test files by default.

## Affected files and checkpoint

User authorizes a five-minute feasibility slice with minimal testing. Build an
isolated domain selector prototype, not another transport/query hint. Measure
one bounded read-only selector comparison if ready. It must not be wired into
the page until all filters/counts/details/export semantics are covered. Report
remaining work at the time boundary; no release or new schema authorized.

Likely operations/apps/core/views.py, coverage_reads.py and/or coverage.html;
final scope follows evidence. Existing uncommitted handoff/measurement updates
and unrelated untracked scripts are preserved. No effective fix achieved.

## Confirmed evidence and rejected candidates

Full standalone read-only profile: 6.417 s instrumented handler, 2.400 s SQL
execution and 1.300 s fetchall, including 42,944 timestamp conversions (1.094 s
inclusive Django loader time). Rendering was 0.555 s; platform-cell construction
0.581 s inclusive. Instrumented costs are not independent/unprofiled HTTP shares.
Plans: initial observations perform 22,937 device lookups and 17 source-driven
bitmap scans; page timestamps repeat observation scanning 17 times with 289
bitmap heap scans. Hudu lifecycle performs 4,896 protected per-record lookups.
No single microquery accounts for the entire page.

Compact requirement transfer and combined source facts preserved complete HTML
(CSRF masking only) in repeatable-read comparisons but were insufficient:
4.762 vs 5.983 s initially; revised candidate 4.187 vs 4.399 s. A materialized
shared Computer input hit the eight-second statement limit and was rejected.
Global nested-loop disabling was worse (6.859 vs 6.170 s). Targeted disabling
for the two observation queries preserved HTML but remained 4.761 vs 5.841 s.
No candidate demonstrated the desired fast page. No serving files or live data
changed; all runs used separate temporary modules and read-only transactions.

User requested a rethink and imposed a four-minute boundary. Speculative runtime
edits were withdrawn to HEAD after saving a local temporary patch; no candidate
was committed/pushed. Exact host/container staging removed. Production remains
.28. Do not revive these candidates as a validated fix.

Next: review existing live index definitions/visibility and the actual protected
observation plans before proposing a covering metadata access path or a maintained
compact domain reader. Any index/schema or new maintenance lifecycle requires
explicit approval. Do not promise a sub-two-second result from those proposals
without representative plans, full parity and candidate measurements.

## Five-minute feasibility slice

Added isolated operations/apps/core/coverage_selection.py prototype; it is not
imported by the serving page. It selects maintained/protected Computer, source,
Hudu and requirement keys into compact SQL stages and computes basic filtered
counts, platform record counts and ordered IDs. Full filter grammar, requirement
cards, detail/export integration and parity are not complete. No schema changes.

Minimal validation: Ruff lint/format and Django base system check. One bounded
read-only prototype comparison on production, eight-second statement limit,
failed with SQLSTATE 57014 before selector output. Therefore no parity or speed
claim; no retries or second campaign. Connection closed and exact staging removed.
The prototype is untracked/unreleased and must not be activated or shipped as a
working fix. Existing serving runtime files have no substantive diff from .28.

Time boundary: report that more time is required. Next inspect the prototype's
nonexecuting plan to identify the expensive join/materialization, then establish
a viable measured selector before wiring additional filters or page details.

## Three-minute extension — viable selector core

One nonexecuting JSON plan identified the prototype-specific failure: UNION
platform-name cardinality estimated at 7,687, leading to a 3,159,357-row matrix,
total estimated cost 1,174,172 and 233 JIT functions. This is separate from the
deployed page's bottleneck. Changed the equivalent platform-set construction to
UNION ALL followed by one materialized GROUP BY; no platform names are truncated.
Selector then completed in 1.107 s. Diagnostic comparison initially failed to
decode the adapter's JSON string; normalized it at the reader boundary and
represented absent aggregate buckets as zero only for comparison to the legacy
explicit zero buckets. Follow-up completed in 1.285 s, with all six checks equal:
Computer total, filtered total, filtered client total, filtered Hudu total,
ordered first 100 IDs, and non-Hudu platform record-status counts. 5,732 Computers
in the repeatable-read runtime-role snapshot. No customer values emitted.

This is selector-core feasibility, NOT full-page latency or complete parity.
Requirement cards, Hudu card categories/links, complete legacy status/agent/Hudu
filter grammar, page clamping, detail hydration and CSV integration remain open.
Existing serving view is unchanged; prototype remains untracked and unconnected.
No migration, release, commit or push. Exact temporary staging removed.

Resume checkpoint: continue from coverage_selection.py, preserve measured core,
complete missing semantics before wiring page IDs to existing bounded detail
readers. Do not ship until filter/output/export parity and complete request timing
pass. Testing remains minimal and targeted; no new test files were created.
Recommend a fresh session using this record and operations/BLUEPRINT.md; reconcile
Git/diffs first, and do not reconstruct prior trial transcripts.

## Next three-minute item — Hudu selection

User authorizes three minutes for the next item. Extend only the isolated
selector with Hudu categories, current/archived link-subset matching, and Hudu
filters. Preserve the legacy rule that record-category filtering activates only
when in_hudu is selected. No serving wiring, schema or release. One bounded
representative comparison if ready; remaining filter/detail/export scope stays open.

Hudu item completed in the isolated selector: category modes any/has_current/
has_archived/current_only/archived_only/both; in/not-in scope; link presence
restricted to the matching current/archived record subset; all four Hudu card
categories. Aggregate existence/count flags do not expand card links/URLs before
pagination. Existing protected readers, ownership/client matching and tenant
predicates retained. Invalid category normalizes to any, unknown scope/link
values are discarded, matching existing normalization.

Minimal runtime verification: default and current_only+has_links scenarios in
separate read-only repeatable-read snapshots, eight-second statement bounds.
Default selector 1.207 s, 5,733 Computers; combined filter 1.249 s, 4,484 matches.
All seven checks pass for both: Computer total, filtered total, client total,
in-Hudu total, exact ordered first 100 IDs, non-Hudu record counts and all Hudu
category counts. No entire filter matrix or full-page timing claimed. Ruff passes;
exact host/container staging removed, no customer fields emitted or data changed.

Checkpoint/next: Hudu selection/counts are implemented but not serving. Next add
normalized agent/record/rule/status filters and S1 exemptions, preserving AND/OR
semantics and legacy bookmarks. Then page clamping, remaining requirement cards,
bounded detail integration and complete CSV. No commit/push/deployment authorized.
Recommend continuing from this checkpoint in a fresh session due context size;
verify Git status/diffs rather than replaying prior diagnostics.

## Five-minute item — agent/status/exemption selection

User authorizes the next bounded implementation slice. Extend the isolated
selector with normalized agent conditions (AND across conditions, OR within
each status list), live stored-verdict status resolution and S1 exemptions.
Reuse the serving view's normalization at integration; do not invent bookmark
translation here. Minimal source checks and one representative read-only parity
comparison. No serving wiring, release or schema change.

Implemented normalized agent record/rule conditions, coverage-source status
conditions and S1 exemption selection in coverage_selection.py. AND across
conditions; OR within each list; Required also includes Missing/Stale. S1
exemption overrides the displayed SentinelOne rule, not the stored verdict or
legacy coverage status. Requirement status uses stored verdicts and current
presence grouped by entity type/named or any platform, with existing severity
priority. Request/bookmark normalization remains owned by the serving view.

Minimal verification: default selector 1.689 s with all seven prior checks equal.
First combined-condition version hit eight-second deadline because correlated
conditions rescanned status rows; replaced with one materialized matched-ID
calculation per condition family. One follow-up representative combination:
Ninja Online record + Required rule + legacy Ninja Online coverage + not-exempt
S1, 2.303 s, 2,955 matches from 5,733 Computers. All seven checks equal to the
existing view: totals/clients/Hudu, exact first 100 IDs, record cards and Hudu
categories. This filtered selector exceeds two seconds; no full-page speed
claim or exhaustive filter/edge certification. No new test files or suite.

Checkpoint: normalized agent/coverage/S1 conditions implemented, still isolated.
Next remaining global state/any-platform/Computer-scope and text filters, full
requirement cards, pagination clamping and detail/CSV wiring. Optimize the
filtered selector before claiming the target. No commit/push/deployment; exact
temporary staging removed. Recommend a fresh session from this checkpoint;
reconcile Git/diffs and preserve unrelated recovery scripts.

## Resume item — global selection, cards and pagination

Added global requirement platform/state selection, any-platform status union,
no-platform presence exclusion and all eleven Computer scopes. Scope values OR
within their group; groups AND together. Any-platform checks both requirement
and source states rather than letting a requirement hide source evidence.
Product scopes use registered agent products; reporting scopes retain client
offline windows. Requirement-card applicability and Missing buckets preserve
SentinelOne exemption precedence. Page numbers clamp like Django get_page:
invalid input goes to page one; nonpositive/out-of-range input goes to the last
page, with one empty page when no rows match.

One bounded production diagnostic in a standalone process used the existing
runtime role, read-only repeatable-read snapshot, eight-second statement bound
and sixty-second process bound. Two scenarios: default and combined reporting
scopes + Ninja Missing + any-platform Online + oversized page. All seven checks
passed in each: total Computers, filtered total, clients, Hudu, ordered page
IDs, clamped page and per-platform requirement-card applicability/Missing
buckets. Selector times 2.619/2.627 seconds; neither full-page timing nor target
achievement. Only these representative scenarios are certified. Existing view
rendering was intercepted in that diagnostic process to capture context; no
serving file, data or shared cache changed. Connection closed and exact host/
container staging removal verified. Docker inventory on the workstation did
not respond and was stopped; no local database workload ran.

Local Ruff lint/format, Python compilation, Django base system check (repository
root on PYTHONPATH), registry validation and git diff --check pass. Dockerfile
copies operations/apps recursively, so the new module is packaged automatically.
No test files or dependencies changed. Sources text, request normalization
integration, complete output/detail/CSV parity, edge cases and complete request
latency remain open; keep the candidate unconnected. Earlier slice results above
describe earlier selector revisions and do not certify this revision's timing.
