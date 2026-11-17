# PLAN-056 — Numbered assessment checklist

## Current position

Post-release checkpoint, 2026-11-11: the four approved fixes shipped in
0.144.11 / `ae45b463`; the earlier no-implementation statements below describe
the pre-fix assessment direction. The
[post-release protocol](PLAN-056-release-acceptance.md) now owns the staged
acceptance proposal and results. Approved Stage A completed: Coverage full-page
first/repeat measured; Home latency target failed. Cold/background execution
retains separate gates. No numbered item is completed by release alone.

Restored 2026-11-10 from the original 12-item assessment list in the earlier
conversation, with status checked against repository evidence and the user's
current decisions. The conversation supplies the original numbering, not proof
of completion. This checklist owns assessment-item tracking; the registry owns
plan lifecycle status, and the blueprint links here for the current action.

**Current direction: step 4, compare and sequence fixes for demonstrated problems.**
User-selected steps 1, the [shared-work map](PLAN-056-shared-work-map.md), and 2,
[background amplification](PLAN-056-background-amplification.md), are complete
as local source reviews. Step 3 [resource interaction](PLAN-056-resource-interaction.md)
is deferred by user direction until larger fixes are in place. Retained
synthesis did not establish causal page/Job interaction; root TODO.md owns
the deferred investigation and resume conditions.
The [bounded correlation protocol](PLAN-056-resource-correlation-execution.md)
was approved once but stopped before sampling because no reviewed Job was
running; cleanup verified, no retry. Step 4's [comparison](PLAN-056-recovery-path-comparison.md)
should now compare established defects without waiting on interaction evidence.
No implementation is approved. This four-step direction
is separate from the numbering below. Original item 6 remains pending, not completed or
silently waived. Item 5's four representative filter pairs completed. Items
1–4 are accounted for, not all successfully measured.
No implementation is approved. Candidate remedies remain separate from this
checklist; identifying a fix does not complete the remaining assessment.

## The original 12 items and current status

1. **Coverage completion — complete.** Determine whether the timed-out request
   finished or left database work running. Surviving work was identified;
   authorized cancellation/retry completed and transactions closed. This is
   completion/cleanup evidence, not successful page latency.
2. **Coverage page-load time — measured post-fix.** Approved Stage A on
   2026-11-11 completed HTTP 200 first/repeat responses in 7.191/6.104 s, with
   exact server-completion markers. The earlier 120-second timeout remains an
   incomplete observation. Cold state, content parity and broader acceptance
   remain unverified; see the post-release results.
3. **Ordinary-user timings — unavailable.** Measure user-accessible pages with
   an existing non-admin account; current results are admin-only. User confirmed
   no non-admin account exists. Revisit if one is introduced.
4. **Controlled cold navigation — deferred until after a fix.** Distinguish
   first-load costs from warm application/navigation-cache costs. Current
   first/repeat samples do not establish cache state. User deferred this item;
   no temporary server or request was started. No approval is pending.
5. **Remaining filter variants — complete for representative scope.** Four
   first/repeat filter pairs completed with HTTP 200 and exact server-completion
   markers: Computers/Windows, Source Records/agent.rmm, Patching/server and
   Software/high risk. See the [execution record](PLAN-056-filter-variants-execution.md).
   Existing page-two observations remain separate; this is not exhaustive
   filter, content-parity or CSV certification. Logout and exact cleanup verified.
6. **Browser loading — incomplete.** Measure assets, JavaScript, rendering and
   when pages become usable. Current timings end when HTML finishes downloading.
7. **External network path — incomplete.** Measure through the normal
   user-facing connection, including network and proxy overhead. Current
   requests use internal loopback.
8. **Remaining page-cost breakdown — partial.** Attribute slow responses to
   queries, shared navigation/context work and rendering, especially Coverage,
   Software, Patching and Source Records. Coverage's lifecycle bottleneck and
   several components are diagnosed; the complete frontier remains open.
9. **Per-job write costs — partial.** Measure writes during identifiable job
   runs and distinguish content changes from freshness/timestamp updates.
   Static writer/consumer tracing and overlapping global counters exist;
   those are not isolated per-job write measurements.
10. **Database contention — incomplete.** Measure lock waits, blockers,
    transaction duration and overlap with Jobs/page requests. Runtime-role
    visibility is limited; queue wait categories do not establish SQL waits.
11. **Refresh costs — partial.** Measure derived-state and activity-summary
    refresh duration/resource use within the ingest workflow. Refresh callers,
    input dependencies and time-relative semantics are traced; live duration
    and resource attribution remain unmeasured.
12. **Storage and retention pressure — partial.** Measure current
    table/index/TOAST sizes and activity age distribution to assess growth and
    retention options. Retained metadata/history does not complete current
    age/size and retention assessment. No retention period or delete is approved.

## Evidence and continuation

- [Assessment evidence](PLAN-056-platform-performance-assessment.md): HTTP,
  resource, Coverage completion/diagnosis and access results.
- [Read attribution](PLAN-056-read-attribution.md): component findings/limits.
- [Write/freshness review](PLAN-056-write-freshness-review.md): local writer,
  timestamp-consumer and refresh findings; no live cost attribution.
- [Measurement protocol](PLAN-056-measurement-protocol.md): execution limits,
  existing measurement authorization and deferred items.

The earlier move to a final remedy comparison was premature. The subsequent
user-directed big-picture synthesis now provides a conditional recovery-path
comparison, without declaring this assessment complete. Coverage and
relationship-history synchronization remain candidates; original item 6 and
the remaining numbered assessment stay open. Do not renumber around deferred
items or mark code review as a completed runtime measurement.
