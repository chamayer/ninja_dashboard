# Metabase parity audit

**Purpose:** Inventory of every dashboard the stack bootstraps into Metabase,
classified against current Operations coverage, to support phased Metabase
retirement under root decision 0005. This is a retirement audit, not a plan to
improve Metabase.

**Method:** Metabase content authored by this stack is defined in
three bootstrap modules under `ingest/`. Those files are the
authoritative "what we produce" inventory. Before a domain cutover, an
aggregate-only production audit must also enumerate operator-authored
questions in the Metabase backing store without exposing query text, result
data, or customer identifiers. Each required capability receives an accepted
Operations path or an explicit retirement decision; pixel-for-pixel parity is
not required.

**Sources:**

- `ingest/metabase_bootstrap.py` (~246 named specs, ~9 dashboards) —
  Ninja patching surface.
- `ingest/inventory/metabase_bootstrap.py` (~13 named specs,
  5 dashboards) — inventory surface.
- `ingest/agent_compliance/metabase_bootstrap.py` (~24 named specs,
  8 dashboards) — legacy AC surface.

**Classification key:**

- **COVERED** — Operations has a native equivalent that operators use
  today. Retiring the Metabase dashboard removes duplication only.
- **PARTIAL** — Operations covers the intent but the specific
  presentation / slice differs. Retiring the Metabase dashboard
  requires a small Operations extension to close the gap.
- **GAP** — no Operations equivalent. Retiring the Metabase dashboard
  requires a real Operations build-out.
- **RETIRED** — already marked retired in the bootstrap; not part of
  the parity requirement.

---

## Ninja patching (`ingest/metabase_bootstrap.py`)

The largest surface. Nine dashboards, of which two are already
marked retired in `_RETIRED_DASHBOARD_NAMES`.

| Dashboard | Classification | Notes |
|---|---|---|
| `Ninja — Command Center` | **PARTIAL** | Operations Home + Findings queue + Devices fleet cover most of the intent. Command-center layout ("triage from one screen") isn't reproduced 1:1. Gap: a patching-focused command view. |
| `Ninja — Overall Patching Status` | **RETIRED** | Not part of the parity requirement. |
| `Ninja — Client Patch Review` | **PARTIAL** | Client detail scoreboard exists but doesn't have a patch-focused rollup. Gap: patching tab on Client detail summarizing approved / stalled / never-patched counts. |
| `Ninja — Patch Evidence` | **GAP** | Per-patch evidence tables (which KBs, which devices) have no Operations equivalent. Building this needs a new surface — probably a `/patches/` route with filter + detail. |
| `Ninja — Device Detail` | **COVERED** | Device detail 5-tab (0.55.0) has a Patching tab. Coverage is close; verify field-for-field if the tab renders everything operators referenced from Metabase. |
| `Ninja — Device Patching Status` | **RETIRED** | Not part of the parity requirement. |
| `Ninja — Device Work Queue` | **COVERED** | Operations Findings queue with `category=patching` filter is the native surface. Already in prod. |
| `Ninja — Patch Trends` | **GAP** | Time-series trend dashboards (per-day installs / failures / reboots / patching-devices) — no Operations equivalent. Requires building trend views (client_health_trend_current landed in 0.49.0 gives a pattern to follow). |
| `Ninja — Activity Search` | **GAP** | Free-text search across patch activity events. No Operations equivalent. Small standalone slice — a search view over a fact table. |

**Ninja patching gap summary:** ~5 gaps ranging from small (Activity Search) to
Track-sized (Patch Trends, Patch Evidence). Client Patch Review closes with a
Client-detail extension.

---

## Inventory (`ingest/inventory/metabase_bootstrap.py`)

Five dashboards.

| Dashboard | Classification | Notes |
|---|---|---|
| `Inventory - Overview` | **RETIRED** | Owner accepted retirement; Operations Home and Devices already cover the useful intent. |
| `Inventory - Devices` | **RETIRED** | Owner accepted retirement; Devices is the native Operations surface. |
| `Inventory - Identity Review` | **RETIRED** | Owner accepted retirement; superseded by `identity_conflict` findings and `device_merge`. |
| `Inventory - Serial Quality` | **RETIRED** | Owner accepted dashboard retirement without a parity gate. Generic serial evidence/data-quality remains forward Operations work, not a Metabase cutover prerequisite. |
| `Inventory - Source Records` | **RETIRED** | Owner accepted dashboard retirement without a parity gate. The generic source-evidence administration surface from decision 0010 remains forward Operations work. |

**Inventory retirement summary:** all five dashboards were explicitly accepted
for retirement on 2026-08-03. Generic Serial Quality and Source Records remain
Operations design requirements but no longer gate this Metabase disconnect.

---

## Agent Compliance (`ingest/agent_compliance/metabase_bootstrap.py`)

Eight dashboards — the entire legacy AC surface. This is the module
Operations was rebuilt to replace (per `project_operations_rebuild`
memory).

| Dashboard | Classification | Notes |
|---|---|---|
| `Agent Compliance - Today` | **COVERED** | Operations Home + Findings queue with `category=coverage` filter give the same "what's wrong right now" view. |
| `Agent Compliance - Devices` | **COVERED** | Devices fleet page with coverage-shaped filters. |
| `Agent Compliance - Device drilldown` | **COVERED** | Device detail 5-tab has coverage state per Agent product. |
| `Agent Compliance - Alerts` | **COVERED** | Findings queue is the alerts surface. |
| `Agent Compliance - Customers` | **PARTIAL** | Client detail scoreboard covers the intent. May need a per-client coverage summary table if operators depend on the tabular view. |
| `Agent Compliance - Setup` | **COVERED** | Requirement profiles + coverage requirements admin (Track C) is the native surface. |
| `Agent Compliance - Health` | **PARTIAL** | Ingest / evaluator health signals — Operations has some (admin health page) but not the full AC-era view. Gap depends on which specific panels operators still reference. |
| `Agent Compliance - Debug` | **GAP** | Ad-hoc query surface for AC-internal debugging. Not operator-facing; retire outright rather than parity-build. |

**AC gap summary:** 2 partials (Customers, Health) and 1 outright
retirement (Debug). Broadly, AC is well-covered by Operations — the
rebuild delivered on parity for the operator-facing surfaces.

---

## Aggregate gap summary

**GAP (needs Operations build-out before Metabase can retire this
piece):**

- Ninja: Patch Evidence, Patch Trends, Activity Search

**PARTIAL (small Operations extension):**

- Ninja: Command Center layout, Client Patch Review tab
- AC: Customers tabular summary, Health panels

**COVERED (retire Metabase surface, no Operations work):**

- All the rest.

**RETIRE OUTRIGHT (no Operations equivalent needed):**

- Ninja: Overall Patching Status, Device Patching Status (already
  retired in bootstrap)
- Inventory: all five dashboards (owner-accepted retirement on 2026-08-03)
- AC: Debug

---

## Recommended sequencing

Retirement happens by domain, gated on accepted Operations capability or an
explicit retirement decision. No phase adds Metabase features or performance
work:

1. **Immediate retirement candidates** (no Operations work needed):
   AC Alerts, AC Today, Inventory Overview, Inventory Devices,
   Ninja Device Work Queue, Ninja Device Detail — verify operators
   are actually using the Operations equivalents in production first.
2. **Small partials** (bounded Operations extensions):
   AC Customers tabular view, Ninja Client Patch Review tab.
3. **Bounded gaps** (single-slice Operations builds):
   Ninja Activity Search.
4. **Larger gaps** (their own tracks):
   Ninja Patch Evidence, Ninja Patch Trends.
5. **Metabase itself** (final): once every operator-facing Metabase
   surface has an accepted Operations path or explicit retirement decision.

Inventory is the first domain cutover. All five dashboards are retired by the
owner's explicit decision. The same approved cutover stops Inventory bootstrap
and refresh calls while leaving legacy relations unchanged for a bounded
rollback window. Generic Serial Quality and Source Records continue outside
the Metabase retirement gate.

This doc is a working plan — update classifications as parity work
lands.

---

## Method notes

- Dashboard-level classification above is the executive view.
- **Per-metric enumeration** (all named specs, grouped by dashboard,
  with source-file line numbers) lives in
  [`metabase-parity-audit-full.md`](./metabase-parity-audit-full.md).
  Use it to verify no individual KPI or card is lost when a
  dashboard is classified as COVERED or PARTIAL — walk the list,
  confirm each metric has a native Operations equivalent, escalate
  the ones that don't. **234 unique specs enumerated across the
  three bootstrap modules** (123 Ninja patching + 24 Inventory + 87
  Agent Compliance).
- Classifications reflect a best read of Operations state as of
  version 0.69.0. Operators should validate whether each COVERED /
  PARTIAL classification matches their actual usage before any
  Metabase surface is deleted.
- The audit is intentionally read-only — no Metabase writes, no
  Operations behavioral changes, no schema changes.
- The pre-cutover production audit enumerates operator-authored questions only
  in aggregate. It must not disclose query text, result data, or customer
  identifiers.
