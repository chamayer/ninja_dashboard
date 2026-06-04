# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Convert single-select dashboard filter dropdowns to **multi-select**
so an operator can pick a few values at once (e.g. "MANUAL +
DELAYED", "Workstation + Server"). Existing Patch Detail Status
filter + clicking the REJECTED pie slice is sufficient for
analyzing REJECTED patches — no new tables / scalars / probes
needed.

## Why

Operator-driven. Current dropdowns force one-value workflows; the
operator wants to combine buckets in a single dashboard load.

## Scope

**In:**

- Add a `_param_multiselect` helper that emits a dropdown with
  `isMultiSelect: True` so the operator can pick multiple values.
- Convert these dashboard parameters from single-select to
  multi-select:
  - **Patch Detail**: Status, Install Outcome, Device Type,
    Severity, OS Family.
  - **Org Overview**: Device Type, OS Family, Severity.
  - **Device Patching Status** (PCOV): Patching Status,
    Device Type, OS Family.
  - **Patch Command Center / Overall Status / Trends**: Device Type.
- Update the SQL filter predicates from `[[AND col = {{var}}]]` to
  `[[AND col IN ({{var}})]]`. Safe for both single-value (Metabase
  passes one quoted string → `IN ('one')`) and multi-value
  (`IN ('a','b','c')`).

**Out / not doing:**

- New Rejected Patches table or scalar — operator confirmed
  existing Patch Detail filter + pie-slice click-through is
  enough.
- Rejected reason / actor probing — same reason.
- "Exclude these values" filters — Metabase has no native pattern;
  parked.
- Org filter on Patch Detail — leave single-select; an operator
  selects one client at a time.
- KB Number — stays single text (no `IN` change, no multi-select).
- Device filter on Patch Detail — stays single (you pick one
  device to drill, not many).

## Honest unknowns / risk

- **`isMultiSelect: True` JSON shape.** Documented in Metabase
  references; some versions also accept `values_query_type: list`
  with extra config. If our shape is ignored the filter falls
  back to single-select — annoying, not broken. First-time use of
  the key in this codebase.
- **Substitution semantics.** Metabase category multi-select
  substitutes the value list as comma-separated quoted strings
  inside the SQL — so `IN ({{var}})` works. Confirmed via
  Metabase community examples but first use in this codebase.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Add `_param_multiselect` (just sets `isMultiSelect: True`
      on top of the existing dropdown shape).
    - Replace `_param_dropdown` with `_param_multiselect` in:
      - `build_detail_parameters` (Status, Install Outcome,
        Device Type, Severity, OS Family — but NOT Org / KB /
        Device / Days).
      - `build_org_parameters` (Device Type, OS Family, Severity
        — but NOT Org).
      - `build_pcov_parameters` (Patching Status, Device Type,
        OS Family — but NOT Org).
      - `build_command_parameters` (Device Type).
      - `build_overall_parameters` (Device Type).
      - `build_trends_parameters` (Device Type — NOT Days).
    - Change every relevant predicate's `=` to `IN (...)`:
      - `_FILTER_PREDICATES` (Detail) — only the multi-select
        columns (status, node_class, severity, os) — leave org / kb.
      - `_PCOV_FILTERS` (PCOV)
      - `_ORG_FILTER_DEVICE_TYPE` / `_ORG_FILTER_OS_FAMILY` /
        `_ORG_FILTER_SEV_CS` / `_ORG_FILTER_SEV_LIR`
      - `_OVERALL_DEVICE_TYPE_FILTER`
      - `_CMD_DEVICE_TYPE_FILTER`
      - `_TRENDS_DEVICE_TYPE_FILTER`
- `CONTEXT.md` — short note near the compliance section pointing
  operators at Patch Detail (filter by Status = REJECTED) and the
  Current Patch State pie's grey REJECTED slice (clickable) as
  the places to audit REJECTED.

## Steps

1. Add `_param_multiselect` helper.
2. Convert Patch Detail params + predicates (largest surface).
3. Convert Org Overview params + predicates.
4. Convert PCOV params + predicates.
5. Convert Command Center / Overall / Trends params + predicates.
6. Update CONTEXT.md with the REJECTED-audit note.
7. Compile-check after each batch.
8. Bump VERSION → 0.13.8, update CHANGELOG + SESSIONS, commit + push.

## Status

*done* — committed as v0.13.8 (pending push).
