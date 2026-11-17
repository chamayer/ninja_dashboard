# PLAN-056 — Recovery-path comparison

## Current status — step 4, prioritize demonstrated problems

2026-11-11 continuation: the user approved the exact Coverage join correction
and focused synthetic PostgreSQL tests. That slice is now implemented locally;
see the [implementation and validation record](PLAN-056-coverage-implementation.md).
The planning-only statements below describe the earlier authorization state.
Other fixes, external validation, commit and deployment retain separate gates.

Subsequent approval: the relationship-history equality guard and its focused
PostgreSQL tests are also implemented locally. See the
[guard implementation record](PLAN-056-relationship-history-implementation.md).
Remaining proposals are unapproved; neither local fix establishes platform recovery.

Third slice subsequently approved and implemented: CVE matcher difference
persistence with focused tests, retaining full candidate recomputation and safety
refresh. See the [matcher record](PLAN-056-matcher-implementation.md) and ADR-0057.
Remaining proposals and release/external work retain their gates.

### Next proposed slice — Home Issues summary

After the three local fixes, prioritize the request-local Home Issues reader
`issue_selection.home_data()`. The retained component pass reached its three-second
statement deadline; the non-ANALYZE plan does not identify its actual cost share.
Existing uncommitted compact-query changes in `issue_selection.py` reduce summary
projection and unnecessary grouping work. They are preserved candidate work,
not approved or measured remediation.

Proposed scope: review and finish only those Home Issues query simplifications
and their focused regression/PostgreSQL parity checks. Preserve the shared Issues
selection contract, independent-action deduplication, covered findings, critical
and mapping populations, category totals and attention links. Leave the existing
Home cache, Software changes, middleware and migration outside this slice.
No new cache, schema, index, shared view or dependency is proposed.

Local synthetic parity can establish semantics, not full Home latency. Runtime
benefit and the cold Home response target remain subject to separately approved
external verification. Implementation and test edits require approval for this
specific slice; no runtime/test or external changes were made during this review.

Subsequent approval and completion: the user approved the Home Issues query slice
and focused tests. The inherited simplifications passed expanded local parity
checks without further behavioral edits. See the
[Home Issues implementation record](PLAN-056-home-issues-implementation.md).
The prior approval-pending statements above describe the planning checkpoint.

### Next proposed slice — Home Software summary

The retained Home Software timeout makes it the next reader candidate after
Home Issues. The existing uncommitted `software_review.home_summary()` candidate
counts only distinct installed titles on current Computers, removing approval/
risk classification. Its matching `views.home` edit replaces the Software card's
approval/risk breakdown with the governed open Software & security action count.
This changes displayed detail and the summary's return fields; it must not be
represented as a transparent query-only optimization or adopted without approval.

Proposed approval scope: review/finish that lean reader and explicit Home card
detail change, with focused title-population PostgreSQL and request/template
checks. Preserve the installed-title population and Software destination; leave
Software page classification and all cache/middleware changes outside scope.
No dependency, schema, index or shared-view change is proposed. Actual production
speed and the full Home latency target remain unverified. This source review
made no runtime/test edits or external calls.

The user deferred resource-interaction investigation until larger fixes are
in place. Compare and sequence remedies for demonstrated problems now; unknown
interaction is not a prerequisite. Root TODO.md owns the deferred investigation
and its resume conditions. Capacity/scheduling remedies remain conditional on
evidence relevant to those decisions. The prior implementation/test approval
request remains withdrawn; this direction authorizes planning, not a fix.

## Conclusion and authority

### Brief prioritization — 2026-11-11

First proposed implementation slice: **Coverage's initial Hudu lifecycle join**
in `operations/apps/core/views.py:fleet_coverage`. Use the correlated lookup
already exercised by `plan056_coverage_candidate.py`, retaining both tenant and
observation predicates, `OFFSET 0`, existing lifecycle policy and left-join
semantics. No shared-view, schema, index, cache or dependency change.

Reason: actual plans establish repeated broad lifecycle work; the full candidate
completed with 4,870 rows and matched all six projected fields and multiplicities
against an independent current-tenant reference. This is stronger evidence than
the unmeasured benefits of the other candidates. It does not certify full-page
latency, future policy cases or other tenants/roles.

Validation scope: existing focused Coverage tests, Python compilation and
applicable Django checks; inspect the diff to preserve earlier unrelated edits.
Any new PostgreSQL tests need their existing separate approval. After separately
approved external/deployment validation, verify a complete Coverage response,
content and cold/repeat behavior. Do not replay the unrestricted slow original.
No new universal latency claim or target is introduced.

Second proposed slice: null-safe equality suppression for the six copied
relationship-history fields, preserving population-wide stale-history repair.
Its runtime benefit remains unmeasured. Broader reader/publication redesign and
resource interaction are not prerequisites to the first slice.

This fulfills the requested brief prioritization and scope definition; it does
not authorize runtime/test edits, commit or deployment. Current Git HEAD remains
`ca00938a`; earlier runtime work is preserved. The active handoff is updated for
a fresh session before implementation; no further assessment phase is required.

2026-11-10: big-picture step 4, local synthesis of the linked source reviews
and retained measurements. HEAD remains `ca00938a`; existing Home, Issues,
Software, middleware, migration and test edits remain uncommitted and preserved.
Rechecked the Coverage diagnostic transformation and relationship-history writer
against current files. No new runtime measurement or implementation.

**Recommend the bounded Coverage lifecycle lookup as the first implementation
slice for approval.** It has a demonstrated execution mechanism, an already
usable index and complete current-tenant result parity. Relationship-history
equality suppression is the next narrow candidate, with unmeasured runtime
benefit. Neither is an adopted fix or a claim of platform-wide recovery.

The [assessment checklist](PLAN-056-assessment-checklist.md) remains authoritative
for unfinished measurements. This comparison completes big-picture step 4;
it does not complete original items 6–12, waive deferred items 2/4, or change
the absence of a non-admin account. No new external protocol is awaiting approval.

## Alternatives and proposed order

Priority below reflects mechanism, confidence and scope, rather than a predicted
percentage speedup. Concurrent counters cannot establish a platform benefit.

| Recovery path | Evidence and expected reach | Contract, risk and decision |
| --- | --- | --- |
| **1. Correct Coverage's Hudu lifecycle access path** | Original actual plans repeatedly process 43,838 lifecycle rows per Hudu record. Full correlated candidate performs 4,870 point-scoped lookups and completes; all six fields and multiplicities match an independent full reference. | Narrow request-local SQL change. Preserve the authoritative lifecycle view, security barriers, tenant predicates, ownership and left-join semantics. Best first slice; full-page latency and other roles/policies remain unverified. |
| **2. Suppress equal relationship-history assignments** | A nonzero endpoint-resolution result triggers synchronization of all visible open history joined to current evidence. Six copied fields lack equality guards. | Prefer considering a null-safe six-field difference guard over restricting to this invocation's changed IDs: the latter removes existing wider stale-history repair. Review triggers and history invariants before implementation approval. Does not prove lower page latency or solve all relationship writes. |
| **3. Reduce attributed reader work on Home and domain pages** | Inventory costs 1.716 s in one direct pass; Home Issues, Patching and Software each hit separate 3 s statement limits. Sources record counts and Source Records page selection also hit limits. | Select one exact reader/query at a time. Existing plans are estimates for most of these; do not infer JSON, sorting or a particular join is the whole cause. Preserve action selection, masking, companion populations and filters. Home's local cache is unshipped work, not a measured solution. |
| **4. Persist CVE match differences** | Matcher deletes/reinserts tenant matches before detecting material differences. This proves replacement work even when final content is equal. | Larger writer change: preserve unique keys, removals/empty input, atomic results, change history and reclassification targets; review row identity and matched-at consumers. Actual write/resource savings unknown. Safety publication has additional mutable/time-based inputs and cannot use match membership alone as its gate. |
| **5. Share summaries or narrow producer/publication scope** | Repeated reader aggregates and tenant-wide readiness/exposure behind named-title work are mapped. No targets deliberately means whole-fleet reconciliation. | Requires explicit population, freshness, invalidation, expiry and failure/recovery contracts. Adds publication work and may introduce schema/operational cost. Do not assume Home, navigation and detail-page totals are interchangeable or change no-target work to no-op. Compare after narrower corrections and relevant phase attribution. |
| **6. Change Postgres memory, host capacity or concurrency** | Retained host windows have CPU/RAM headroom; Coverage consumes roughly a core. Global reads/temp files coexist with slow pages, but ownership and physical-device pressure are unresolved. | Conditional only. Attribute waits, spills, device I/O, worker occupancy or pressure before sizing or changing admission. Preserve Jobs dependencies, claim guards and finding-write safety. More workers may multiply expensive work; memory settings multiply across operations/connections. No settings or hardware proposal selected. |
| **7. Retain less activity data / maintenance** | Historical size evidence and moving-window rollup consumers are retained, but current age/size distribution and cost remain incomplete. | A separate lifecycle decision inside PLAN-056, not an emergency speed claim. Preserve timeline/search requirements and expiry behavior; define retention/archive policy before a delete. Deletion need not return disk space to the OS. No period, delete, vacuum/rewrite or rebuild approved. |

The findings index inherited from PLAN-049 remains a conditional reader remedy:
it targets Computers' active-finding lookup, not Coverage's demonstrated join.
Its historical branch has a migration-number conflict. Verify/rebase it only
under a separately approved slice; do not bundle it into the first correction.
Previously prepared matcher reuse likewise remains inherited evidence, not an
excuse to release unrelated work together. The
[consolidation record](PLAN-056-consolidation.md) retains these scopes and gates.

## Requirements that constrain every route

- Keep tenant isolation, RLS, view security boundaries and restricted metadata
  masking. Existing admin-only results cannot certify ordinary-user parity.
- Preserve distinct populations: governed actions, patch tiles, source health,
  companion-excluded source records and Coverage are different contracts.
- Preserve successful observation/evaluation freshness, ownership revision and
  queue-generation fences, missing-row cleanup and atomic finding publication.
  Readiness assessed-at affects exposure expiry. Equal content is insufficient
  to skip every write or refresh; moving windows change without new input.
- Retain Home's inherited goal of ordinary response at most 1.5 s and 2.0 s
  hard maximum, including cold navigation. Its accepted summary age up to 60 s
  does not waive miss-path latency. Do not extend that staleness allowance to
  every page or domain. No new numerical target is invented for Coverage.
- Keep the derived-stage completion-policy discrepancy visible in the
  [shared-work review](PLAN-056-shared-work-map.md). Changing exception policy
  is a separate correctness decision, not part of a query correction.

No new durable architecture decision is adopted here. Summary storage, typed
source facts, heartbeat separation and scheduling contracts require their own
decision records if selected; proposals remain in this record.

## Concrete first slice for review

Proposed runtime file: `operations/apps/core/views.py`, only the initial Hudu
lifecycle join inside `fleet_coverage`. Apply the already diagnosed
`candidate_sql` transformation in
[the candidate diagnostic](../../scripts/diagnostics/plan056_coverage_candidate.py):
replace the broad lifecycle left join with a `LEFT JOIN LATERAL` selecting
`record_lifecycle` from the same view, correlated on both tenant and observation
ID, retaining `OFFSET 0`, joined `ON TRUE`. Keep the outer filters, grouping,
projection, source/Computer/ownership joins and all later page phases unchanged.
The optimization fence is deliberate: the actual candidate plan evaluates
policy for each requested observation instead of broad repeated lifecycle work.

This proposal requires no new dependency, index, grant, migration, schema,
cache, shared-view or public-interface change. Existing unrelated edits in the
large views file must remain intact and be excluded from this slice's review.
Runtime packaging already copies this file; confirm the build path when editing.

Proportional validation after implementation approval:

1. Run existing focused Coverage checks in `test_coverage.py`, Python compilation,
   applicable Django checks, registry validation and whitespace review. Mocked
   cursor checks verify composition/render behavior but cannot prove PostgreSQL
   lifecycle execution or isolation.
2. **Separate test-file approval requested with the slice:** add focused synthetic
   PostgreSQL coverage for current/archived/unmatched policy states and tenant
   isolation, comparing original/reference and candidate row multisets. This
   fills the future-policy/other-tenant gap left by current-tenant live parity;
   avoid a test that merely asserts the SQL contains `LATERAL` or `OFFSET`.
   Reuse an existing suitable fixture/harness after inspecting it; no fleet
   copy or local performance benchmark. Stop if that needs broader fixture or
   migration changes and bring back the concrete scope.
3. After separate external approval, verify the changed deployed source and
   completed full Coverage response with server completion, then the deferred
   repeat/cold checks. Reuse retained original evidence; no unrestricted slow
   original replay. Any temporary diagnostics need reviewed bounds and cleanup.
4. Review pending migrations and mixed-worktree release contents before separate
   commit/push approvals. Push approval must cover automatic deployment and the
   actual pending migrations, even though this slice introduces none. Do not
   release all preserved changes by default.

A passing query comparison is insufficient for page acceptance: later Coverage
reads, shared context, Python assembly and rendering can still dominate. A full
response timeout remains failure to establish latency; stop and diagnose the
next phase under bounded approval. Reversion scope is this join change; do not
remove lifecycle policy or security as a fallback. Deployment/rollback requires
its applicable authorization.

## Remaining platform work and checkpoint

Keep browser usability and external connection-path measurements open (6/7),
remaining reader attribution partial (8), and per-job writes, SQL contention,
refresh cost and retention assessment open/partial (9–12). Resolve each under
its own bounded protocol when it can change a decision or certify acceptance.
Do not force another broad pre-fix campaign to justify the demonstrated Coverage
correction, or use that correction to close unrelated assessment items.

Next action: obtain approval for the exact Coverage implementation slice and
its stated synthetic test gap, or continue a user-selected open assessment
frontier. Planning authorization alone does not permit either runtime/test
edits or new production diagnostics. PLAN-056 remains active.

Evidence: [Coverage actual plans and complete parity](PLAN-056-platform-performance-assessment.md#confirmed-mechanism-and-full-reference-result),
[read attribution](PLAN-056-read-attribution.md),
[writer/freshness contracts](PLAN-056-write-freshness-review.md),
[scope amplification](PLAN-056-background-amplification.md), and
[resource limits and interaction](PLAN-056-resource-interaction.md).

Validation: local source/diagnostic review and documentation checks only;
no tests, runtime edits, live measurements or new performance claims.
