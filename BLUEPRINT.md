# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Add current device reachability to the Device Summary table as an
`Online?` column next to `Last Contact`.

## Why

Operator requested it after clarifying that `Active Devices` is based
on last contact, not the current up/down signal. The device summary
table already shows `Last Contact`; surfacing reachability alongside
it makes the distinction obvious.

## Investigation

`ninja_core.v_active_devices` already carries the latest snapshot's
`offline` flag, so the SQL can derive an `Online?` display without a
schema change.

## Scope

**In:**
- Add `Online?` to Device Summary.
- Use a clear yes/no/unknown display derived from `offline`.
- Update release docs.

**Out / separate investigation:**
- Any broader rollout to other tables unless the user asks.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Add the `Online?` column to the Device Summary query.
- `CHANGELOG.md`
    - Document the new reachability column.
- `SESSIONS.md`
    - Record the dashboard change.

## Steps

1. Patch the Device Summary SQL.
2. Compile-check.
3. Update CHANGELOG / SESSIONS.
4. Commit and push, then report the short hash.

## Status

in progress
