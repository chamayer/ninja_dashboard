# Active Operations work plan

Track: **Unified Operations navigation**

## Status

- Complete. The compact two-tier navigation and custom Operations Admin
  landing are in place; Django Admin remains separate.

## Goal

Make primary workflows, client context, and the three Operations Admin groups
discoverable from a proportional two-tier navigation shell.

## Scope

- **In:** shared navigation, custom Admin overview, client breadcrumb row, and
  focused navigation tests/validation.
- **Out:** replacing Django Admin, changing permissions, or restructuring the
  underlying Review/Config/Integrations pages.

## Decisions

- Django Admin remains `/admin/`; the custom Operations landing is
  `/admin/overview/`.
- The top row is for fleet workflows. The second row is contextual: selected
  client navigation or Operations Admin group navigation.
- The existing group tab strip remains on Admin pages for in-group detail;
  the global second row solves cross-group navigation.

## Steps

- [x] Add Operations Admin overview and route.
- [x] Replace inline client links with a compact second navigation row.
- [x] Add persistent Admin Overview/Review/Configuration/Integrations links.
- [x] Reduce header and nav height; validate URLs/templates.

## Validation plan

- Django checks, URL reversal/template loading, focused tests, format/diff
  checks, and manual review of the shared template diff.

## Checkpoint

- The current top-level Admin link opens the Client Candidates queue, while
  Config and Integrations are only visible after reaching a page in that group.
- Client context is appended to the main navigation row, producing an
  oversized, visually unbalanced header. The dedicated second-row work was
  recorded in the backlog but not shipped.
- `/admin/overview/` is the custom Operations landing; the top-level Admin
  link leads there while the gear and explicit context-row link retain Django
  Admin at `/admin/`.
- Scoped client pages now expose `Clients › <client>` and the related actions
  in the second row. The duplicated scoped overview/configuration breadcrumbs
  were removed from page bodies.
- Validation: Django check, URL reversal, template loading, focused
  client-workspace tests (8), import/format checks, and diff check pass.
- Follow-up fixed: the client-row More dropdown was clipped by horizontal
  scrolling. Its Users, Locations, History, and Policies destinations are now
  ordinary second-row links.

## Next action

- None.
