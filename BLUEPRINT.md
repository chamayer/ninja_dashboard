# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Switch custom-field ingest to the scoped Ninja API feed and keep only
the allowlisted field names from `.env`.

## Why

The current ingest path only walks `/queries/custom-fields`, which is
device-centric. We now know the scoped endpoint returns organization
and device records in one feed, so the ingest can collect both without
fan-out by org or per-device inheritance calls.

## Scope

**In:**
- Use `/queries/scoped-custom-fields` as the custom-fields ingest
  source.
- Honor `INGEST_CUSTOM_FIELDS_INCLUDE` as the field allowlist feed.
- Keep device, organization, and location scopes in the ingest path.
- Preserve pivoted `v_<entity>_custom_fields` views.
- Update docs so the source-of-truth / behavior is clear.

**Out / separate investigation:**
- Dashboard UI wiring for the new custom-field columns.
- New custom-field definitions metadata model.
- Changing the semantic meaning of the fields the user created.

## Files to change

- `ingest/core/custom_fields.py`
  - Switch the fetch path, add scoped-query params, keep allowlist
    filtering, preserve pivot generation.
- `ingest/probe_fields.py`
  - Optional follow-up if needed to inspect the scoped feed instead of
    only the legacy device-centric feed.
- `CONTEXT.md`
  - Update the custom-fields ingest description to match the scoped
    feed.
- `CHANGELOG.md`
  - Record the ingest-source change.
- `SESSIONS.md`
  - Note the reasoning and what was verified.
- `TODO.md`
  - Move any deferred dashboard wiring into Backlog if it appears.
- `VERSION`
  - Bump for the ingest behavior change.

## Steps

1. Update the ingest module to read from scoped custom-fields.
2. Keep the env allowlist as the field feed and pass it to the API.
3. Verify the regenerated device/org/location views still work.
4. Compile-check the Python module.
5. Update docs and version.
6. Commit and push after approval.

## Open questions

- None for the ingest change itself; dashboard wiring remains a
  separate follow-up if needed.

## Status

in progress
