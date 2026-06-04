# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Refocus the patch KPIs around the MSP operator question: what share of
active devices are currently patching, and what share are fully
patched.

## Why

The current cards mix device counts, patch-work completion, and device
outcome. The command center should keep the raw count cards, but the
headline KPI should answer "are devices actively patching right now?"
and the status/detail pages should pair that with the fully-patched
share.

## Scope

**In:**
- Keep the Command Center count cards.
- Rename the Command Center headline KPI to `Actively patching %`.
- Show `Actively patching %` and `Fully patched devices %` on Overall
  Status and Org Overview.
- Update the Trends dashboard to show both rates.
- Update release docs and versioning.

**Out / separate investigation:**
- Reworking the underlying patch-state classifier.
- Adding new data sources or schema changes.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Rename the KPI cards, add the new active-patching percentage,
      and align trend labels.
- `CONTEXT.md`
    - Update the operator-facing metric definitions.
- `VERSION`
    - Bump for the dashboard update.
- `CHANGELOG.md`
    - Document the KPI split and label changes.
- `SESSIONS.md`
    - Record the dashboard rework and rationale.
- `TODO.md`
    - Move any deferred follow-up into Backlog if one appears.

## Steps

1. Rename the relevant card titles and SQL aliases.
2. Keep the count cards on Command Center and swap in the new
   headline percentage.
3. Update Overall Status, Org Overview, and Trends to show the two
   operator KPIs.
4. Compile-check the bootstrap.
5. Update docs and version.
6. Commit and push, then report the short hash.

## Open questions

- None.

## Status

in progress
