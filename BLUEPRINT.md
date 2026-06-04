# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Make every card on Patch Detail honor every applicable filter.

## Why

Operator-reported. Patch Detail is the filterable-list workhorse;
the operator expects all 8 cards to narrow when any of the 9
filters change. Currently two gaps:

1. Device filter is declared as a dashboard parameter but the
   shared SQL predicate fragment doesn't include it. When the
   operator picks a single device, the other cards keep showing
   the whole fleet.
2. `detail_installs_timeline` inlines its filter predicates with
   the old single-select `= {{var}}` syntax — it was never
   converted in v0.13.8. So Status / Device Type / Severity /
   Install Results / OS Family don't multi-select on the
   timeline chart.

## Scope

**In:**

- Add `[[AND d.system_name = {{device}}]]` to `_FILTER_PREDICATES`
  (single-value `=` since Device is single-select).
- Replace the inlined predicates in `detail_installs_timeline`
  with `{_FILTER_PREDICATES}` + the days predicate. That way the
  timeline picks up multi-select for free and stays in sync with
  every other Detail card.

**Out / not doing:**

- Adding new filters. Just ensuring existing ones reach every card.
- Touching cards on other dashboards.

## Honest unknowns / risk

- None I can see. Both edits are mechanical and the patterns are
  already in use elsewhere on this page.

## Files to change

- `ingest/metabase_bootstrap.py`
    - `_FILTER_PREDICATES`: add `[[AND d.system_name = {{device}}]]`.
    - `detail_installs_timeline` query: collapse the inlined
      predicate block into `{_FILTER_PREDICATES}` + the days line.

## Steps

1. Edit `_FILTER_PREDICATES` to add the Device predicate.
2. Rewrite `detail_installs_timeline` query.
3. `python -m py_compile` check.
4. Bump VERSION → 0.13.9, CHANGELOG + SESSIONS, commit + push.

## Status

*done* — committed as v0.13.9 (pending push).
