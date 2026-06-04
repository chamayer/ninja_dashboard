# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

(1) Audit and close any remaining filter-reach gaps on dashboards
beyond Patch Detail.
(2) Demote Needs Reboot from a top-row scalar on Command Center /
Overall Status / Org Overview to the action-queue tables.

## Why

Operator-driven.
- v0.13.9 closed the Patch Detail filter gaps; expecting the same
  bug pattern may exist elsewhere.
- Needs Reboot earns top billing only on a device-health view,
  not on patch-management dashboards. Failed / Manual / Stalled /
  Never-Patched are more actionable in a patching context. The
  Devices Needing Reboot tables stay as the operator's reboot
  action queue.

## Scope

**In:**
- Audit Shape A: every dashboard's shared SQL filter fragment
  should include every parameter the dashboard declares. Compare:
    - `_ORG_TAGS` ↔ `_ORG_FILTER_*`
    - `_PCOV_TAGS` ↔ `_PCOV_FILTERS`
    - `_CMD_TAGS` ↔ `_CMD_DEVICE_TYPE_FILTER`
    - `_OVERALL_TAGS` ↔ `_OVERALL_DEVICE_TYPE_FILTER`
    - `_TRENDS_TAGS` ↔ `_TRENDS_DEVICE_TYPE_FILTER`
- Audit Shape B: any card SQL that inlines `[[AND ... = {{tag}}]]`
  instead of using the shared fragment. Cards that inline get
  stale when filter rules change (the bug behind v0.13.9).
- Fix anything found in the same commit as the Needs Reboot work.
- Remove the top-row Needs Reboot scalars:
    - `cmd_reboot` (Command Center)
    - `overall_reboot` (Overall Status)
    - `org_reboot` (Org Overview)
- Re-flow each Devices row from 5 tiles at 5+5+5+5+4 to 4 tiles
  at 6+6+6+6.

**Out / not doing:**
- Touching Device Patching Status (no Needs Reboot scalar there).
- Removing any reboot tables / columns / Trends chart — they're
  the right surface for reboot actions.
- Adding a new Device Operational Health dashboard (future, only
  if operator demand).

## Audit findings

- **Shape A (declared-but-not-filtered):** clean across every
  dashboard. Earlier script "MISSING" hits were false positives
  (`id` / `display-name` are nested dict keys, not tag names;
  `days` / `pcov_days` are window params consumed directly by
  each card's CTE, not via the shared filter fragment).
- **Shape B (inlined `[[AND` predicates):** clean — every `[[AND`
  in the file lives in a shared filter constant. The `_DEVICE_FILTER`
  hard-binding for Drilldown is intentional.
- **Found and fixed one self-inflicted bug:** the v0.13.9 fix
  added `[[AND d.system_name = {{device}}]]` to
  `_FILTER_PREDICATES` without noticing it was already present at
  the bottom of the same fragment. Removed the duplicate.

## Honest unknowns / risk

- The Devices Needing Reboot tables and `cmd_clients` Needs
  Reboot column already exist and are unaffected. The only risk
  is a layout mistake during the reflow.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Remove the three `_reboot` scalar dicts.
    - Adjust `col` / `size_x` on the four remaining Devices-row
      scalars (Active, Patching, Stalled, Never-Patched) per
      dashboard to 6 each starting at col 0/6/12/18.
    - Remove the three `_reboot` keys from `_SCALAR_ALERT_RULES`.
    - Plus anything the audit turns up.
- `BLUEPRINT.md` — Status → done after push.
- `CHANGELOG.md`, `SESSIONS.md`, `VERSION` → 0.14.0 (MINOR bump for
  the layout change).

## Steps

1. Run Shape A audit (compare tags vs filter predicates).
2. Run Shape B audit (grep for inlined `[[AND`).
3. Apply any fixes found.
4. Remove the three Needs Reboot scalars + reflow rows.
5. Remove the three keys from `_SCALAR_ALERT_RULES`.
6. `python -m py_compile` after each batch.
7. Bump VERSION → 0.14.0, update CHANGELOG / SESSIONS, commit + push.

## Status

*done* — committed as v0.14.0 (pending push).
