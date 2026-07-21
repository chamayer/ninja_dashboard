# Active Operations work plan

Track: **Software-analyzer gap track** — close the six gaps from
`operations/docs/legacy-scripts-parity-audit.md` where
`script-dev/ninja/SW Inventory/analyze_inventory.py` (3041 lines) has
capabilities Operations doesn't yet.

## Status

- Planning — 6 gaps enumerated; phased execution proposed; awaiting
  scope confirmation before Phase 1 execution.

## Goal

Bring Operations to parity with the analyze_inventory.py capabilities
that are actually useful to operators, so the script can eventually
retire from the mental toolbox (per project rule: scripts stay
available; Operations covers the monitoring/decision surface).

Explicitly **not** in scope: Excel / VBA / VBS output. Operations is
web-only.

## Gap enumeration

Data source columns:

- **Data ready** — data exists in Operations; only UI + query needed.
- **Data needed** — external integration.

**Correction (2026-07-21):** the `analyze_inventory.py` script consumes
a **Ninja-side CSV export** produced by `Ninja_sw_inventory.ps1`, not
PDQ Inventory. Same source Operations already ingests continuously
via `ingest/inventory/software.py`. No new ingest source is needed
for the software gaps — everything the script does with the CSV,
Operations can do with the live data. PDQ-ingestion phase dropped.

| # | Gap | Data | Size | Notes |
|---|---|---|---|---|
| 1 | **Publisher rollups + publisher-level decisions** | Data ready | Small | `software_installations_current` has publisher; add a Publishers page + publisher-scope `SoftwareDecision`. |
| 2 | **Whitelist Suggestions surface** | Data ready | Small | Threshold-based query over installations + decisions: "N software titles are on ≥ X machines and currently unclassified." Rendered as an operator queue with per-row Approve/Reject/Investigate. |
| 3 | **Tech Checklist** | Data ready | Small-Medium | Curated per-device cross-reference: rare software + suspicious matches + no-decision items. One view per device; export CSV. |
| 4 | **CVE / vulnerability enrichment** | Data needed | Medium-Large | External integration (NVD JSON feed or similar). New ingest module + `software_cves` table. Enrichment column on the software catalog. Own ADR. |
| 5 | **User-risk analysis** | Data ready | Small-Medium | Requires user ↔ installation join. Ninja already publishes `lastLoggedInUser` per device (in `ninja_core.device_snapshots` custom fields or similar); wire the join. New matview or view. |

## Proposed phasing

### Phase 1 — Quick wins (data ready, small UI slices)

Ship items 1, 2, 3 as one arc. All build on existing
`software_installations_current` + `software_decisions` +
`software_catalog`. Each is a new page + view + optional evaluator.

- **1a**: Publishers page — list of publishers with device / title
  counts + publisher-level decision surface.
- **1b**: Whitelist Suggestions queue — configurable threshold; new
  view + queue; reuses `software_decisions_queue` action pattern.
- **1c**: Tech Checklist — per-device curated report; new page under
  device detail (6th tab) or standalone `/software/checklist/`.

Each shippable independently; likely 2-3 version bumps total.

### Phase 2 — CVE enrichment

Needs a proper ADR:

- Integration target (NVD 2.0 API vs local mirror vs alternative feed
  like OSV / CVE.org).
- Refresh cadence + caching strategy.
- Match strategy (publisher+name+version → CVE list).
- Surface: enrichment column on Software fleet page + per-title CVE
  detail view + a `software_cve_high_severity` FindingType.

Own decision record + own execution plan. Multi-day slice.

### Phase 3 — User-risk analysis

Needs a small design decision:

- User model — Operations has `ClientUser`; Ninja publishes
  `lastLoggedInUser` per device. Wire the join.
- Risk framing — "which users have suspicious software" implies
  we've already scored suspicious via the classifier. Reuse the
  existing severity signals.
- Surface: per-user software report + a `high_risk_user`
  FindingType if desired.

Bounded slice once the user↔device join is decided.

## Files involved (Phase 1 only)

- `operations/apps/core/views.py` — new views:
  `publishers_page`, `publishers_decide`, `whitelist_suggestions_queue`,
  `tech_checklist_page`.
- `operations/config/urls.py` — 4 new routes.
- New templates: `publishers.html`, `whitelist_suggestions.html`,
  `tech_checklist.html`.
- No new models — reuse `SoftwareCatalog`, `SoftwareInstallation`,
  `SoftwareDecision`.
- Version bumps: 3 sub-slices (1a/1b/1c) probably ship as
  0.75.0 / 0.76.0 / 0.77.0.

## Decisions

- **Phased approach** — smaller Phase 1 first, larger Phase 2/3/4
  gated on separate ADR + user greenlight per phase.
- **Reuse existing decision model** — `SoftwareDecision` already
  supports global / per-client / per-device scope. Publisher-level
  decision doesn't need a schema change if we add a scope='publisher'
  variant, OR we treat "publisher approve" as pattern-matched via
  the existing `SoftwareClassifierRule` machinery.
- **Tech Checklist as a standalone page** rather than a Device
  detail tab — the checklist is a report artifact, not part of the
  device's daily state.

## Validation

- Django check + ruff after each Phase 1 sub-slice.
- Manual smoke: each new page renders, CSV export works, sort works.
- Real prod verification of query performance on the software tables
  (they can be large; may need EXPLAIN pass before shipping if any
  slice's query looks heavy).

## Current checkpoint

- Stack version 0.74.1.
- Patching-visibility track closed (0.73/0.74/0.74.1). All patch
  gaps at Operations parity.
- Software-analyzer track: planning-only; awaiting Phase 1 greenlight.

## Remaining blockers

- User confirmation of the Phase 1 scope + sub-slice ordering.
- Later: user approval for Phase 2 ADR + Phase 4 ADR when we reach
  them.

## Next action

- Confirm Phase 1 scope with user (this doc), then execute 1a → 1b
  → 1c as separate small commits + version bumps. Phase 2/3/4 each
  gets its own decision record + plan when opened.
