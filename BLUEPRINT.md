# PLAN-001 — Dashboard navigation performance

## Goal

Make ordinary Dashboard navigation responsive from measured causes, with current
deployed evidence or an explicit measured exception.

## Scope

Dashboard and landing-page server/rendering performance. Preserve tenant/RLS,
URLs, card meanings, and existing data authorities. No cache, duplicate
projection, speculative index, migration, or production-data action.

## Status

Completed with a measured exception. Releases 0.128.1–0.128.15 are deployed;
the latest performance releases are mirrored by commits `e671685` and
`6ec8b35`.

## Evidence and decision

Dashboard warm handler timing is 1.308–1.568 s; Sources is 0.935–0.988 s;
Software Overview is 1.042–1.068 s; Products is 2.037–2.082 s. User exposure
browser first response improved from 4.302 s to 2.961 s after its bounded view.

Computers first response improved from 6.351 s to 4.740 s (4.942 s duration,
375 KB transfer). Its handler assembly fell from 7.525 s to 4.610 s. Hudu
fleet facts fell from 2.054 s to 0.989 s; page-only Hudu presentation is
0.071 s. The next release removed 80,164 full-fleet URL encodes, which a
full-render profile had measured at 4.634 s.

The remaining full-render profile measures 3.154 s database wait across the
15 fleet reads and 1.209 s template rendering; full-fleet status-cell work is
only 0.579 s. Reaching the two-second target would require an approved shared
inventory read model or a changed full-fleet filter/card contract. That work
is deferred rather than introducing an unapproved projection or weakening the
operator contract.

## Validation

`pytest apps/core/tests/test_coverage.py -q` passed (14 tests), as did
`manage.py check`, `compileall`, plan-registry validation, diff whitespace,
and governance validation. Governance retains the known stale
`docs/current-state.md` status-date warning. No schema or data changes.

## Follow-up

Open a new approved plan before designing an inventory read model or changing
the full-fleet filter/card contract.
