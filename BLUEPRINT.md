# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Audit the dashboard query layer for performance bottlenecks and remove
the worst repeated-filter / repeated-join patterns.

## Why

The Device Patching Status page gets slow when multiple filters are
combined, especially `Patching Scope`. The dashboard needs the same
scope behavior, but with fewer repeated scans through
`ninja_core.v_active_devices`.

## Scope

**In:**
- Remove correlated `patching_scope` lookups where the query already
  has the needed scope data.
- Reuse derived scope columns inside shared CTEs where that reduces
  repeated scans.
- Keep the existing dashboard behavior and filters intact.

**Out / separate investigation:**
- Any offline-device cleanup.
- Reworking existing docs beyond the new reference file.

## Files to change

- `ingest/metabase_bootstrap.py`
  - Remove repeated scope checks and keep the slow pages on one scan
    path.
- `BLUEPRINT.md`
  - Track this task while it is in progress.
- `SESSIONS.md`
  - Record the dashboard update once it is done.

## Steps

1. Patch the bootstrap to remove the remaining correlated scope
   filters.
2. Re-scan the query layer for the next obvious bottleneck.
3. Compile-check the bootstrap.
4. Update the session log.
5. Commit and push after approval.

## Open questions

- None.

## Status

in progress
