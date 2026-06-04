# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

(1) Audit every dashboard's filter coverage: which parameters are
declared, which cards honor them, are there gaps? (2) Decide the
*right* filter set per dashboard and add what's missing. (3) Make
every multi-value dropdown actually multi-select (Org included).
(4) Honestly address the "nav bar above filter" position request.

## Why

Operator reports Command Center cards don't appear to honor the
Device Type filter. Even if they technically do, the filter set on
high-level dashboards is thin — Command Center has only one
filter, which doesn't match operator expectations.

## Investigation (run before any code changes)

- Confirm whether `_CMD_TAGS` / `_CMD_PARAM_MAPPINGS` are reaching
  every card on Command Center, and whether
  `{_CMD_DEVICE_TYPE_FILTER}` is in every card's SQL. (Earlier
  v0.13.6 wiring should have done this — verify.)
- Same audit per dashboard.

## Proposed filter set per dashboard

| Dashboard | Filters today | Proposed filter set | Action |
|---|---|---|---|
| **Patch Command Center** | Device Type | **Org · Device Type · Severity** | ADD Org + Severity |
| **Overall Patching Status** | Device Type | **Org · Device Type · OS Family · Severity** | ADD Org + OS Family + Severity |
| **Org Overview** | Org · Device Type · OS Family · Severity | (same) | none |
| **Device Patching Status** | Org · Device Type · OS Family · Patching Status · Stale-days | (same) | none |
| **Patch Detail (Filterable)** | Org · Device · Status · Device Type · Severity · Install Outcome · OS Family · KB · Days | (same) | none |
| **Trends** | Days · Device Type | **Days · Org · Device Type · Severity** | ADD Org + Severity |
| **Device Drilldown** | Device · Days | (same — per-device, no slicing) | none |

Why these picks:

- **Org filter is the strongest "scope" knob.** Operator usually
  works one client at a time. Adding Org to Command Center,
  Overall, and Trends matches that workflow.
- **Severity matters on high-level views** for "show me the
  Critical-only situation". Useful on CC, Overall, Trends.
- **OS Family on Overall** lets the operator quickly compare
  Win 11 vs Win Server compliance at a glance. Less useful on CC
  (action queues) so skipped there.
- **Patch Status filter excluded from CC / Overall / Trends** —
  those dashboards' cards ARE the status breakdown. Filtering by
  status would defeat the purpose.

## Multi-select scope

Convert ALL applicable single-select dropdowns to multi-select:

- **Org** — currently single-select everywhere; change to
  multi-select. (Operator picks 2-3 clients to compare.)
- **Device** on Patch Detail — keep single-select (one device is
  always the natural drill).
- **Days** — keep single-value number input.
- **KB Number** — text input, stays single (multi-text would be a
  CSV which is awkward; multi-select with text input doesn't fit
  Metabase well).

All other dropdowns already multi-select per v0.13.8. New
parameters added in this task default to multi-select.

## Nav bar above filter — honest answer

Metabase renders the dashboard parameter bar **above** the dashcard
grid. Dashcards (including markdown / heading virtual cards like the
nav bar) live INSIDE the grid. There is no built-in way to place
a dashcard above the parameter bar.

Options:

- **(A) Accept the current order** — parameters at top, then nav
  bar, then content.
- **(B) Move nav bar to bottom of each dashboard** — possible but
  awkward; navigation belongs at the top.
- **(C) Replace the nav bar with Metabase's "Custom Embedded
  Frame" or use a Metabase JWT-based custom landing page** — way
  out of scope.

My recommendation: **(A)**. The parameter bar at the very top is
the standard Metabase UX and operators are accustomed to it.

## Scope (code changes)

**In:**

- Add Org filter to Command Center / Overall / Trends.
- Add Severity filter to Command Center / Overall / Trends.
- Add OS Family filter to Overall.
- Convert Org parameter to multi-select on every dashboard that
  has it (Detail, Org Overview, PCOV, plus the new Command
  Center / Overall / Trends).
- Update all relevant SQL predicates from `=` to `IN (...)` for
  the newly-multi-select Org filter.
- Add per-card wiring (template_tags / param_mappings / SQL
  predicates) for the new Org / Severity / OS Family filters on
  Command Center / Overall / Trends.
- Audit and confirm Command Center existing Device Type filter
  is actually reaching every card.

**Out:**

- Drilldown (per-device).
- Detail's already-complete filter set.
- Any new SQL semantics — just plumbing existing filters into
  more cards.
- Nav bar position change (Metabase constraint).

## Honest unknowns / risk

- Adding Org as a parameter to dashboards that currently use
  cross-dashboard click_behavior with `p_org` may cause subtle
  conflicts. Today's Fleet click on an org bar passes `p_org` to
  the Org Overview's parameter; adding `p_overall_org` to Overall
  itself shouldn't affect outbound clicks but needs a quick check.
- Multi-select Org dropdowns substitute a comma-separated list of
  quoted strings. SQL `IN ()` handles this. Already proven by the
  v0.13.8 work for Status / Device Type etc.
- The `cmd_clients` / `cmd_failed_queue` / etc. SQLs have many
  JOINs; each new filter predicate piles on, which can hurt query
  plan. Acceptable for now; can revisit if dashboards slow down.

## Files to change

- `ingest/metabase_bootstrap.py`
    - New parameter constants: `PARAM_CMD_ORG`, `PARAM_CMD_SEV`,
      `PARAM_OVERALL_ORG`, `PARAM_OVERALL_OS`, `PARAM_OVERALL_SEV`,
      `PARAM_TRENDS_ORG`, `PARAM_TRENDS_SEV`.
    - New filter fragments per dashboard (mirror the existing
      `_CMD_DEVICE_TYPE_FILTER` shape).
    - Update each dashboard's TAGS / PARAM_MAPPINGS dicts.
    - Update each card's `template_tags` / `param_mappings` to the
      expanded constants.
    - Update each card's SQL to apply every applicable filter
      predicate. (For cards that don't currently JOIN the device
      table or org table, add the join — Org filter needs the
      organizations table joined.)
    - Convert Org dropdowns to `_param_multiselect` and predicates
      to `IN (...)`.

## Steps

1. Investigate the Command Center filter wiring; report findings.
2. Walk through each dashboard:
   - Declare new parameters.
   - Expand the filter fragment.
   - Update every card's wiring.
3. Compile-check after each dashboard.
4. Bump VERSION → 0.14.1 (or 0.15.0 if scope warrants — TBD), update
   CHANGELOG / SESSIONS, commit + push, report hash.

## Status

*done* — v0.14.1 (Command Center) and v0.14.2 (Overall + Trends +
Org multi-select on Detail/Org/PCOV).
