# PLAN-056 — Page-scoped Coverage Hudu detail

## Scope and status — 2026-11-17

User approved the page/detail split with a three-minute implementation limit.
Implemented and source-reviewed; user now approved commit/push, including 0418,
and one post-deployment measurement pass. No tests are authorized or run. This is not a latency/correctness certification or completion of
Coverage acceptance.

## Implementation and contract

- New migration 0418 adds
  `operations.read_hudu_computer_inventory_evidence(bigint, uuid[])`.
- It reuses migration 0150's exact Hudu population, projection and relayed-card
  expansion, inserting tenant and observation-ID predicates inside the existing
  materialized input. This avoids per-ID calls around a fleet-materializing view.
- Same `operations_view_owner` boundary as the existing protected view, SQL
  STABLE SECURITY DEFINER with fixed `pg_catalog, operations` search path.
  Supplied tenant must match current tenant through the retained predicate;
  NULL/empty observation lists select nothing. PUBLIC/runtime grants are revoked
  before EXECUTE is granted only to the existing app/read-only reader roles.
  No new role, source-write privilege or public view change.
- `views.fleet_coverage.populate_hudu_presentation` uses that function, deduplicates
  requested IDs and reads batches of at most 100. HTML still calls it after
  filtering and pagination; CSV passes the complete filtered selection through
  every batch. Existing alias labels, record grouping and link presentation stay.
- Full-population compact filtering, stable existing ordering, counts, cards and
  CSV selection remain unchanged. The compact selection is still in Python;
  no SQL selection rewrite is claimed. Source timestamp detail is unchanged.

R1/R2 preserve existing tenant/owner/population semantics; R3 moves the ID boundary
inside the materialized detail input; R4 deduplicates keys and batches expansion.
No cache/new publication/store is introduced. R8 full-request timing remains
unverified; other initial fleet reads can still dominate. CSV detail SQL is batched,
but this does not change or certify the existing full-export buffering behavior.

## Review, packaging and next action

Source-reviewed against migration 0150 and the existing post-pagination caller.
Existing Operations Docker directory COPY includes both changed files. Migration
0418 depends on 0417; rollback drops only the new function. Rollback code must
restore the old view caller before removing the function. Original view/grants
remain unchanged. VERSION/CHANGELOG now prepare the approved 0.144.24 release.

Next: commit and push the approved release (including 0418) to origin, then
mirror. Observe automatic deployment, then measure complete HTML once per page.
The shared badge removal ships in the same release.
User stopped testing; no runtime behavior, plans, permission checks or latency
improvement are claimed from source review alone.
