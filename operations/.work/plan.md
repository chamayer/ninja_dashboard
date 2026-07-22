# Active Operations work plan

Track: **Devices estate dashboard**

## Status

- Complete. Devices now presents estate/freshness context before device
  exploration without becoming a triage queue.

## Goal

Show the shape, freshness, and discoverability of the device estate without
turning the Devices domain into a triage queue.

## Decisions

- Issues, Patching, and Review own work queues. Devices only provides
  contextual status and drill-throughs.
- Offline and not-reporting are distinct device states.
- Legacy/Metabase is validation input, not the page's information architecture.

## Steps

- [x] Add estate/freshness and contextual coverage/identity summaries.
- [x] Use human-readable current state in the device grid.
- [x] Validate focused Devices rendering and queries.

## Validation

- `python manage.py check`, template loading, Python compilation, import
  formatting, and `git diff --check` pass.
