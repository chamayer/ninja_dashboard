# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Stop Metabase card reuse across dashboards so each dashboard keeps
its own card SQL, template tags, and filter wiring.

## Why

Operator-reported. v0.14.3 fixed the obvious tag/mapping parity
mismatch, but the real issue appears to be shared Metabase cards:
cards are currently upserted by display name, and multiple dashboards
reuse titles like `Active Devices` / `Current Patch State`. That lets
later dashboards overwrite earlier card definitions.

## Investigation

Confirmed duplicate card titles across dashboards:

- `Active Devices`
- `Current Patch State`
- `Patching Devices`
- `Stalled Devices`
- `Never-Patched Devices`
- `Failed Patches`

That means title-based upserts can reuse the wrong Metabase card and
leave a dashboard pointing at stale SQL / tag wiring.

## Scope

**In:**
- Add a hidden stable card identity and use it for Metabase card
  upserts.
- Keep visible card titles unchanged.
- Update release docs for the new fix.

**Out / separate investigation:**
- Any live Metabase cleanup of already-orphaned duplicate cards.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Add a stable hidden card UID and make `_upsert_card()` use it
      instead of title-only matching.
    - Include the UID in card `description` so future runs can find
      the right Metabase object.
- `VERSION`
    - Bump to `0.14.4`.
- `CHANGELOG.md`
    - Document the card-identity fix.
- `SESSIONS.md`
    - Record the diagnosis and fix.

## Steps

1. Patch Metabase bootstrap card identity and lookup logic.
2. Compile-check.
3. Bump VERSION → 0.14.4, update CHANGELOG / SESSIONS.
4. Commit and push, then report the short hash.

## Status

in progress
