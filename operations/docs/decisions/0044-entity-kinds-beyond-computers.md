# 0044 — Entity kinds beyond computers

Status: Proposed
Date: 2026-10-25

## Context

Operations matches every source record to a Computer. Records that describe
something else therefore read as "unlinked computers": on 2026-10-25 about
5,200 active records had no Computer, almost all Hudu assets, and most are
not machines at all.

Active records by source and type (production 2026-10-25, read-only):

| Source | Type / Hudu layout | Active | On a Computer |
|---|---|---|---|
| Hudu | Computers | 4,681 | 4,308 |
| Hudu | Servers | 1,642 | 1,086 |
| Hudu | Auvik (network inventory) | 2,863 | 0 |
| Hudu | Printing | 327 | 0 |
| Hudu | Locations | 292 | 0 |
| Hudu | Applications | 150 | 0 |
| Hudu | Special Role Devices | 129 | 0 |
| Hudu | Network Devices | 116 | 1 |
| Hudu | WAN | 115 | 0 |
| Hudu | Mobile Devices | 73 | 0 |
| Hudu | Client Summary, Remote Access, Content Filtering, Managed Certificate, Wireless, File Share, Vendor Summary, Email Summary, Backup | 180 | 0 |
| Hudu | Credit Card | 9 | 0 |
| Ninja | agent.rmm / vm.guest / vm.host / network.device / monitor.target | 5,664 | all |
| LogMeIn, ScreenConnect, SentinelOne, R-U-ON | agents | 9,246 | nearly all |

Entities today: `device` 6,107, `os_installation` 5,169, `asset` 1,425,
`client` 79. 3,784 candidate proposals wait as "observed only: asset". ADR-0012
already says Operations tracks entities, not only computers, that a
non-computer record "needs an anchor of the right class, which the existing
candidate workflow already produces", and that record type to entity class is
registry data, not code.

## Options considered

- Keep matching everything to Computers and hide non-computer records.
- One `asset` class for everything that is not a Computer.
- A small taxonomy: classes where identity works differently, a *kind*
  attribute for variants within a class, and the mapping from each source
  record type to a kind kept as admin-managed data.

## Decision (proposed)

1. **Taxonomy.** Entity classes only where identity differs:
   - `device` (Computer): serial, VM UUID, agents, names (unchanged);
   - `asset` (other hardware): serial or MAC, else name within a client, with
     `kind` = network device, printer, mobile device, special-role device,
     wireless, other;
   - `location` (site): name and address within a client;
   - `service` (application, WAN circuit, remote access, backup, email,
     content filtering, file share, certificate): name within a client, with
     `kind`;
   - `documentation`: records kept as reference only (client summary,
     vendor summary); they create no entity and are not "unlinked".
2. **Mapping is data.** A table maps each source record type (and, for Hudu,
   layout) to a class and kind, with priority and a default of "unclassified"
   (shown, never guessed). Ninja node classes already map through
   `node_class_mappings` and join the same table. Admins edit it; a new
   layout appears as unclassified until mapped.
3. **Sensitive layouts.** A mapping can mark a layout *excluded* (not
   collected) or *restricted* (collected, never shown). Decided 2026-10-25:
   "Credit Card" (9 records) is **restricted**. The `evaluator_config` row
   `restricted_source_layouts` lists such layouts (admin-managed), and the
   safe metadata view returns no name, serial, VM UUID or link for them
   (migration 0345).
4. **Matching per class.** The existing entity-candidate workflow creates and
   attaches anchors of the mapped class, with that class's identity evidence.
   The same printer in Hudu and Auvik becomes one asset.
5. **Relationships.** Computers and assets *at* a location, services *used
   by* a client, assets *connected to* a network device, each a registered
   relationship type (ADR-0012: a relationship may carry attributes).
6. **Inventory by kind.** Source records show each record's class and kind;
   "unlinked" means a classified record without its entity, the only
   worklist. Inventory gains assets, locations and services beside
   Computers.

## Plan

| Phase | What | Needs |
|---|---|---|
| 0 (done, interim) | Source records shows reported name, source group, layout, source links, issue counts and *why unlinked* (migration 0344) | — |
| 1 (decided) | Credit Card restricted: collected, details never shown (migration 0345) | — |
| 2 | Mapping table + admin page; seed from today's layouts; unclassified shown | migration, design review of the seed |
| 3 | Classes `location`, `service` (and `asset.kind`); candidates create anchors by class; measure matches before enabling attachment | migration, rehearsal |
| 4 | Relationship types and their projection | migration |
| 5 | Inventory pages for assets, locations, services; Source records "unlinked" counts only classified records | UI |

Each phase ships on its own and is measured on production first.

## Consequences

- The "unlinked" number becomes meaningful: today's ~5,200 shrink to the
  records that should have an entity and do not.
- New classes need RLS-scoped anchors, as `asset` already has; no unscoped
  entity references a scoped one.
- The identity resolver for Computers is unchanged; other classes match
  through the candidate workflow.

## Supersedes or superseded by

Applies ADR-0012 (structure, mappings in data). Relates to ADR-0040 (records
under the wrong client) and ADR-0043 (one machine or two).
