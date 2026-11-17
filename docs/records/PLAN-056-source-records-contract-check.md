# PLAN-056 — Source Records contract check

Status: bounded check complete, 2026-11-12; candidate remains undeployed.
Production baseline: 0.144.16 / 7cdf0767. No deployment is part of this check.

## Scope and mechanism

Exercise global contract R2/R3/R4/R8 on the default 100-row Source Records page:
select IDs before expensive detail projection and use the existing batch client
attribution function. Existing protected metadata, filters, ordering, counts,
enrichment and template remain unchanged. No new store/cache/publication system.

One real configured-admin HTTP baseline, followed by one isolated runtime-role
current/candidate GET-and-render comparison in the same read-only repeatable-read
snapshot. The diagnostic replaces only the exact reviewed page SELECT in its own
process; it does not modify serving code. Both runs clear only their isolated
LocMem cache and use fresh user objects. Capture complete view context in memory
and compare it, including rows/order, counts, choices and pagination. Print only
timings, result size/counts and equality; no customer values, SQL or credentials.

Candidate timing includes context processors and rendering but excludes real
middleware, session/network handling and browser work. It is not candidate HTTP
acceptance. Same snapshot is not an identical PostgreSQL/OS cache state. Filtered
views, subsequent pages, CSV and other roles are outside this bounded check.

Controls: 15-second statement and 1-second lock deadlines; 65-second process
deadline for the comparison. Stop on failure or mismatch. No retry campaign,
test-file edits, application/schema changes, jobs or deployment.

Artifacts: scripts/diagnostics/plan056_source_records_candidate.py,
plan056_source_records_http.py and the unchanged source-selection/auth helpers.
The handoff retains the three existing local corrections; they are not deployed
or authorized for release by this request to test.

## Result

Executed once using the approved helper and hash-verified temporary scripts in
Operations on 0.144.16. Real configured-admin HTTP baseline at 20:21 UTC: 200,
137,921 bytes in 8.861 seconds; normal logout confirmed.

| Same-snapshot isolated GET/render | Current | Candidate |
| --- | ---: | ---: |
| Full view, context processors and render | 9.214 s | 3.460 s |
| All SQL | 9.007 s | 3.327 s |
| Main page SELECT | 6.410 s | 1.241 s |
| SQL statements | 13 | 13 |
| Rendered HTML size | 137,877 bytes | 137,877 bytes |
| Displayed records | 100 | 100 |

Complete view context equality passed, including all record fields/order, issue
enrichment, totals, source/client/type/layout choices and pagination. Both
responses were 200. Captured values were discarded, and connection closure was
confirmed. Local process caches were cleared separately; PostgreSQL/OS cache
state could differ. Candidate view/render time improved about 62%; main query
about 81%. Neither comparison is a candidate production HTTP measurement.

This supports bounded projection plus existing batch attribution for this
default page. It does not certify other roles, filters, CSV, browser/network,
concurrent changes or a platform-wide fix. Remaining 3.460-second execution is
not a complete performance acceptance claim. No test suite/file edits, serving
code/schema changes, Jobs, commits, pushes or deployment occurred for this check.

Comparison script SHA-256:
3a5a902039a439ac1cdeb87902bb29312b8e7f9099beaa6de38ea2dd3b8d4a06.
HTTP wrapper SHA-256:
57a1de09d7ad255919e731788e065df0263ddba4fe1f8dc89462222ac4835677.
Temporary host/container copies removed after completion. Next: review a scoped
Source Records release if requested; full deployed HTTP acceptance stays open.

## Three-minute remaining-cost check

User requested a bounded remaining-cost check. One further isolated current/
candidate comparison added code-location timing only; no serving-code changes.
Current GET/render 8.962 s, SQL 8.709 s, page SELECT 6.162 s. Candidate GET/render
3.159 s, SQL 3.045 s, page SELECT 1.098 s. Both returned 200, 100 records,
137,877 rendered bytes and identical complete view context; closure confirmed.

Candidate's remaining SQL: total-count read 0.191 s, type choices 0.266 s,
layout choices 0.287 s, row issue enrichment 0.099 s, shared Issues navigation
count 0.865 s, shared Patching count 0.228 s. Other SQL totaled about 0.011 s;
Python/rendering about 0.114 s. This accounts for the request's remaining time,
without establishing absence of infrastructure problems across the platform.

The main correction follows R3/R4 and preserves Source Records domain semantics.
Further work, if authorized, belongs to the shared navigation count owners
(1.093 s) and domain count/facet reader (0.744 s); no new store, cache or
publication framework is justified by this trace alone. No such changes were
implemented or deployed here. Existing isolated/read-only/cache/role/variant
limitations still apply. Three temporary script copies per host/container were
removed after the comparison. No test-file edits or suite runs.

## Final local candidate — 0.144.17

User rejected the 3.16-second result. The scoped extension stays in existing
readers: source_record_views.inventory_facets owns the shared managed-record
predicate and one count/type/layout aggregate. Filtered totals still apply their
original full selection. Source Records selects IDs, projects only displayed
metadata, uses existing batch attribution and bounds group mappings to that page.
HTML disables JIT only within its request transaction after measured compilation
overhead; CSV and server-wide settings are unchanged.

Issues count-only selection narrows intermediates and permits branch predicate
pushdown; Home/wider selection retains its existing materialization. Source-binding
JSON is evaluated only for the type whose join already required it. The existing
Issues owner supplies both navigation totals in one statement: open independent
actions and raw active entity-namespace Patching findings, including the existing
paused/covered semantics. The context processor fills both existing 60-second
cache keys. Home's existing issue total still avoids recalculating that count.
No new storage, services, dependencies, schema, or external interface.

Intermediate isolated checks returned equal complete contexts/badges at 2.507,
2.125, 2.015 and 1.855 seconds as the identified work was reduced. These are
different code/load/cache samples, not comparable production HTTP benchmarks.
Final actual-code comparison against the unchanged deployed handler in one
read-only snapshot, local process caches cleared for each:

| GET/render including context processors | Current | Final candidate |
| --- | ---: | ---: |
| Wall time | 8.741 s | 1.838 s |
| SQL time | 8.496 s | 1.736 s |
| Main page query | 6.0785 s | 0.5998 s |
| Statements | 13 | 14 |
| HTML bytes | 137,877 | 137,877 |
| Records | 100 | 100 |

Complete context and both navigation badges were equal. Candidate facet read
0.3907 s, shared navigation 0.6762 s, row enrichment 0.0616 s. The extra small
statements establish the helper savepoint/context and HTML planning policy; total
database work fell. Source candidates were generated from HEAD plus only the
Source Records function and the three reviewed shared reader modules; unrelated
Home/client-inventory changes were not imported. Connection closure confirmed.
No serving files were modified, and no application deployment occurred.

Acceptance limits: this is configured-admin default-page evidence, not other
roles, filters, CSV, browser/network or a cold PostgreSQL cache guarantee. Full
candidate HTTP is pending a separately approved release. No new tests or broad
suite. Syntax/undefined-name, packaging and isolated-diff checks are the local
release checks. There are no new migrations; local/staged 0413 is excluded.

## Contract review conclusion — release withdrawn

The user requested a conclusion within three minutes. Withdraw the proposed
0.144.17 release and its earlier commit/push questions: its 1.838-second result
included page-specific JIT tuning and was not production HTTP acceptance.
Remove that setting from views.py and restore VERSION/CHANGELOG to deployed
0.144.16. Delete the isolated release index so an obsolete approval cannot
accidentally ship it. Preserve all structural work and original user staging.

The structural changes implement global R2–R4 in existing domain readers:
managed-record identity/population and protected metadata stay authoritative;
the shared predicate supplies global facets, filtered totals retain full filters,
IDs bound metadata/group lookup, and batch attribution retains existing proof.
Shared Issues logic preserves independent actions and raw entity Patching counts.
No competing identity, finding, ownership or publication authority was added.

That is useful partial implementation, not a certified permanent page fix.
The final structural-only variant has not been measured over full HTTP and is
not claimed to meet the user's performance expectation. Prior untuned variants
still exceeded two seconds. The remaining request-time count work and R8 full-
request acceptance must be resolved at their shared/domain owners. No evidence
in this check authorizes declaring the whole environment fixed or introducing
another store/framework. No further tests, production changes or release in
this conclusion step. Software's deployed recovery remains intact.

## Structural-only contract-impact check

User authorized a new bounded comparison with a two-minute limit. Ran one
current/candidate GET/render pair in the same read-only snapshot with empty
isolated local caches. SHOW jit returned on; no planner override was made.
Unchanged serving code remained 0.144.16; only temporary candidate modules ran.

| Measure | Current | Structural-only candidate |
| --- | ---: | ---: |
| View/render | 7.584 s | 2.434 s |
| SQL | 7.330 s | 2.344 s |
| Statements | 13 | 13 |
| HTML bytes | 115,775 | 115,775 |
| Records | 100 | 100 |

Complete context and both navigation badges were equal; connection closed.
Candidate page SELECT 0.7444 s, combined count/facets 0.5014 s, shared navigation
1.0397 s. This demonstrates about 68% improvement from structural changes alone,
but does not establish a two-second/full production HTTP outcome. Role, filter,
CSV, middleware/network and PostgreSQL cache limitations remain. No new tuning,
test-file changes, Jobs, commit, push or deployment. Release remains withdrawn.
Temporary host/container/workstation candidates removed after completion.

## Two-minute shared-navigation feasibility check

User requested a bounded decision on obtaining fast shared navigation. One
read-only same-snapshot actual-plan check used existing deployed and candidate
selectors; both count values matched. No source/serving change or planner override.
Deployed Issues count: 964.285 ms, 61,171 sorted items, about 630 temporary blocks
written, 55,913 finding rows. Proposed combined count: 1100.588 ms, 55,845
finding-state primary-key probes, 574.074 ms JIT compilation (442 functions).
Node times are inclusive/non-additive, not a summed execution breakdown. Baseline
plan covers Issues only; combined query also includes Patching, so these are not
identical-work throughput measurements.

Concrete next correction: use a set-based covered-state selection in the shared
count reader and avoid ranking/materializing irrelevant per-record data. These
plans do not establish that another summary store is necessary. No fix is claimed
from this diagnostic. No indexes/schema, runtime settings, Jobs, commit, push or
deployment changed. The two temporary host/container files and local copy were
removed after completion; no new test suite or test-file edits.

## Issues domain reader count correction — 2026-11-13

User directed implementation of the existing Issues reader count path. The
count-only selector now materializes covered finding IDs/attention once and
joins that set instead of independently probing finding_state for each item.
Other reader paths retain their original state relation. Remove the experimental
cross-domain navigation_counts API; context_processors again consumes Issues
count(Scope(status=open)) and keeps Patching's existing count separate.

One read-only repeatable-read Operations-role check returned the same count:
deployed 1.424 s, local candidate 0.716 s. No JIT override, schema, dependency,
store or producer change. Syntax and focused undefined-name checks passed.
No new unit-test files or broad suite. This is a single count-path check, not
full page acceptance or proof of the proposed 200 ms budget. Local change only;
no commit, push or deployment. Source Records structural work remains local.
Temporary count-check/candidate copies removed after the run.
