# PLAN-056 — Coverage compact-read correction, 2026-11-17

User authorized a five-minute fix after the one-pass bottleneck attribution;
no tests. Implementation and source review complete; user now authorizes commit
and push including 0419, which startup applies automatically. No measurements or
tests for this candidate; performance acceptance remains unverified.

## Changes and compatibility reasoning

1. Migration 0419 adds `read_coverage_source_record_counts(bigint)`. It uses the
   exact base population/source joins of lifecycle view 0158 but omits its unused
   lifecycle-policy lookup. That lookup is a LEFT JOIN LATERAL with LIMIT 1:
   it neither filters observations nor multiplies them. Counting the same base
   observations therefore preserves totals, including unattached and withdrawn
   rows, and the existing agent/VM/CMDB type selection. Grouping remains source
   name, not platform or current Computer. No current/active predicate is added.
2. The count reader has the same operations_view_owner security boundary as the
   lifecycle view, explicit current-tenant/supplied-tenant equality, fixed search
   path and revoked PUBLIC execution. Only app/read-only roles get EXECUTE.
   It returns counts, no source payload or policy bypass for record eligibility.
   Hudu's separate archived/current policy evaluation remains unchanged.
3. Requirement presence uses one GROUPING SETS aggregate instead of a per-platform
   aggregate followed by another aggregate/UNION. The per-platform and 'any'
   populations remain separate, including a real platform named 'any'. BOOL_OR
   semantics, including NULL input, remain; stored requirement verdicts are read
   unchanged, never re-evaluated by the page.
4. Fleet platform cells now return only six compact fields used by filtering,
   cards and agent search. Full presentation cells are still built for the
   selected HTML page and every selected CSV row. Relative-age search behavior
   remains in the compact path. No early population slicing or export truncation.
5. Compute the offline cutoff once per Computer for this request; reuse it for
   status/filter/card decisions. Build cleanup-review URLs only for displayed rows.

All filters, summary denominators, ordering and CSV selection remain at their
existing full-population boundaries. No cache, store, new role or dependency.
These changes remove demonstrated unused work; they do not claim to eliminate
all four measured fleet reads or prove the complete-request latency budget.

## Packaging, rollback and next action

Operations Docker's existing directory copies include changed views.py and
0419. It depends on 0418. Reverse SQL drops only the new function; restore the
old caller before dropping it. Existing lifecycle view/grants are unchanged.
VERSION/CHANGELOG prepare approved release 0.144.25. Source review only; no tests
or repeat measurement. Next: commit, origin then mirror, observe automatic
deployment and confirm 0419 applied. No manual migration or redeploy.
