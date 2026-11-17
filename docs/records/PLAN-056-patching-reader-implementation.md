# PLAN-056 — Patching finding reader optimization

## Goal, scope and authority

User requested optimizing the diagnosed Patching bottleneck in compliance with
[R1–R9](../decisions/0006-platform-read-contract.md). Preserve entity-finding
namespace, tenant/client ownership, category/status/client/device-slice/type
filters, tile semantics, severity/recent-detection ordering and complete CSV.
No new dependency, schema, publication or cache. User subsequently authorized
commit and push; prepare release 0.144.27, origin then mirror, including automatic
deployment. No new migrations. Existing 0420/0421 were confirmed applied on .26.

Affected runtime files: operations/apps/core/computer_reads.py (ownership
predicate), patching_reads.py (selection/order/page reader) and views.py (wiring).
Plan status belongs to the registry; current handoff is operations/BLUEPRINT.md.

## Evidence and decisions

One read-only deployed handler trace after the page remeasurement returned 200:
4.321 s wall, 3.296 s SQL, 14 statements. Finding tiles: 1.6288 s; table finding
fetch: 1.3443 s; posture: 0.2171 s; population: 0.0825 s. This bypassed
middleware/network and does not apportion the earlier 5.481 s HTTP request.
Connection and exact temporary staging closed/removed. No customer data emitted.

Existing findings selection uses a tenant-wide findings-ID ownership subquery
twice, then loads/sorts/formats all matching findings before paginating 50.
Use correlated ownership existence from the Computer domain owner, one filtered
base selector, SQL deterministic ID ordering, page-only detail hydration and
bounded CSV iteration. Tile counts, filtered total and page IDs share one compact
statement snapshot. Preserve existing scope
and all nonfinding posture reads. Add a stable ID tie-breaker where prior equal
severity/timestamp order was unspecified. No persisted model or freshness change.

## Steps and validation

1. Implement scoped selector and bounded HTML/export execution.
2. Run syntax, focused existing checks and representative query/selection review.
   Do not create or modify test files. Local checks must be small correctness
   checks, never fleet timings. Record unavailable services explicitly.
3. Record R1–R9 mechanisms, packaging, actual evidence and limitations.
   Deployed candidate timings require approved release or rehearsal scope.

## Checkpoint

Implemented locally; PostgreSQL execution/performance remains unverified.
Generated SQL review confirms namespace/tenant/category/status predicates and
the subject/client/tenant/state ownership correlation. HTML first materializes
only scalar selection keys; one statement produces tile counts, filtered total
and <=50 ordered IDs. Hydration reapplies the selector to those concrete IDs;
concurrent access changes can remove rows, never widen access. CSV uses the same
ordered selector with 500-row iteration and the existing complete CSV writer.
It still buffers serialized CSV output; it does not retain all Finding objects.
Unknown-client/empty queryset compilation returns completed empty counts/IDs.

R1: existing RLS/namespace/ownership enforced. R2: shared filtered base and
statement-consistent counts/page IDs; hydration rechecks current access.
R3: no finding JSON/related-object enrichment before page IDs. R4: shared
ownership owner/order and compact selection reused for counts/page. R5/R8:
representative execution plan and full-request latency remain open; no measured
speedup or full contract certification is claimed. R6/R7: no prepared result,
new cache or maintenance lifecycle. R9: complete filtered export in bounded
fetch batches, with existing output-buffer limitation above.

Validation: Django base-settings system check passed; SQL compilation and empty
selection path checked without a database. Ruff lint passed for both readers;
patching_reads format check passed; computer_reads file format check did not.
Focused existing tests: 40 passed, five source-text assertions failed; their
same expected snippets are also absent from the relevant HEAD source sections
(device-detail, Home, posture and device-slice assertions). No test files changed.
Local Docker did not respond; its pending listing was interrupted. No candidate
production execution, new timing pass or application-file hotpatch occurred.
Existing Dockerfile copies include all changed modules; no packaging change.

User asked to reduce work, then authorized commit/push. Diff reviewed; prepare
0.144.27 with the recorded validation limits and completed measurement/resume
evidence. Next push origin then mirror and observe automatic rollout; no separate
redeploy or additional timing campaign. Existing unrelated recovery scripts stay
untracked. Broader PLAN-056 acceptance remains open.
