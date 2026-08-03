# 0005 — Operations-first reporting and phased Metabase retirement

Status: Accepted
Date: 2026-08-03

## Context

Metabase was adopted as the read-oriented reporting surface while Operations
was still primarily a write-side control plane. Operations now owns canonical
entities, generic source evidence, derived current state, findings, operator
decisions, and the administrative workflows that consume them. Maintaining
source-specific Metabase materializations in parallel duplicates semantics,
keeps legacy append-history readers on the critical collection path, and can
degrade the Operations service that is replacing them.

The Inventory Metabase module demonstrates the problem directly: its seven
materialized views are consumed only by the Metabase bootstrap in repository
code, but their refresh repeatedly reconstructs current state from legacy
Agent Compliance observation history. Improving that legacy reporting chain
would create throwaway infrastructure instead of advancing the accepted
generic-source architecture.

## Options considered

- Continue optimizing and maintaining Metabase reporting pipelines until all
  Operations parity work is complete.
- Freeze Metabase functionality, build missing capabilities in Operations from
  generic source contracts, and retire each Metabase domain as its Operations
  acceptance gate passes.

## Decision

Operations is the destination for both operational reporting and operator
workflow. Metabase is legacy and will be retired by domain.

Do not add Metabase dashboards, source-specific reporting models, refresh
machinery, or performance improvements. The only permitted Metabase work is
the minimum needed to inventory consumers, preserve rollback, archive or
disconnect an accepted legacy surface, and ultimately remove the service.

Missing capabilities are implemented in Operations against generic current
source records, normalized claims/evidence, canonical entities, findings, and
compact generic rollups. They are not copied from legacy source-specific
schemas merely to reproduce a dashboard implementation.

For each domain cutover:

1. Audit repository-defined and production-authored Metabase consumers without
   exposing customer data.
2. Confirm every required operator capability is present in Operations or is
   explicitly accepted for retirement.
3. Disable the legacy bootstrap and refresh call in the same approved cutover
   that activates the Operations replacement.
4. Preserve legacy tables and materializations unchanged for a bounded rollback
   window. Historical deletion and disk reclamation require a later operational
   approval.

Inventory is the first application of this decision. On 2026-08-03, the owner
explicitly accepted retirement of all five Inventory dashboards without an
Operations parity gate. The bootstrap archives that surface and disconnects
the `ninja_inventory` refresh; its seven materialized views are not optimized
or deleted. Serial quality remains generic evidence/data-quality work, and
Source Records remains the generic source-evidence administration capability
required by the unified entity ecosystem, but neither blocks this accepted
Inventory retirement.

## Rationale

This removes legacy work from the production critical path, prevents competing
semantic authorities, and directs implementation effort toward the generic
source model that future connectors and Operations screens will share. Phased
retirement preserves a safe rollback boundary without allowing rollback data
to remain an active production dependency.

## Consequences

- Operations reporting must use stable generic contracts and tenant-safe read
  models, not Metabase SQL copied into Django.
- Operations parity and usability are acceptance gates for each domain, but
  pixel-for-pixel dashboard reproduction is not required.
- Existing Metabase content may remain temporarily, but it receives no feature
  or performance investment.
- A cutover may archive Metabase content and stop its refresh; it must not
  delete historical storage in the same release.
- Independent Operations availability defects, including expensive Software
  request-time aggregation and duplicate collection entry, still require
  correction even when a Metabase refresh is removed.

## Supersedes or superseded by

Supersedes decision 0002.
