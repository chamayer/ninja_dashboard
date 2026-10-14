# 0028 — Derived device software exposure with live approvals

Status: Accepted

## Context

Device software exposure combines three slow-changing facts: an open software
finding, an installed version with current source support, and a fresh condition
assessment that permits the finding to execute. The prior all-live view rebuilt
that fleet-wide relationship for every operator request. This made unrelated
operator pages slow and tempted page-specific caches.

Approvals are different. They are operator decisions and must remove an
exposure immediately after it is saved.

## Decision

`operations.device_software_exposure_current` is the sole derived read model
for the first three facts. It is rebuildable from findings, installation
evidence, lifecycle policy, and condition assessments. A successful software
classification refreshes it concurrently after those inputs have been brought
to a consistent state. It records evidence and assessment freshness deadlines;
the public view enforces those deadlines live, so data cannot remain actionable
merely because a later collection or evaluation did not run.

`operations.v_device_software_exposure` is the only runtime read surface. It
is tenant-scoped, security-barrier protected, and applies client and device
approval decisions live. No runtime role receives direct access to the
materialized relation.

## Consequences

- Operators see approval changes immediately; no approval is cached in the
  derived relation.
- Classifier completion is the publication boundary for changed exposure
  eligibility. A failed classifier leaves the prior completed projection in
  place rather than publishing a partial result.
- All consumers retain the existing public view and do not implement their own
  finding-to-installation fan-out.
- The relation is derived state, not a second software, evidence, finding, or
  decision authority.

## Amended 2026-10-13

Amended by 0030: exposure is derived from per-device readiness and the aggregate assessment (SQL 114) and refreshed after scoped runs; see 0030 and 0029.
