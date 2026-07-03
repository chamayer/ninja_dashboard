# Goal

Prevent Postgres materialized-view refreshes from failing because the
container has too little shared memory.

# Why

Live log showed `psycopg.errors.DiskFull: could not resize shared memory
segment ... No space left on device` while refreshing
`ninja_inventory.inventory_summary_current`.

# Scope

- Add Docker shared-memory sizing to the Postgres service.
- Record the deployment requirement in version notes.
- Do not change dashboard SQL, inventory SQL, or scheduler behavior in
  this patch.

# Files to change

- `docker-compose.yml` — set `postgres.shm_size`.
- `VERSION` — bump patch version.
- `CHANGELOG.md` — record the Docker/Postgres fix.
- `SESSIONS.md` — record cause, fix, and validation.

# Steps

1. Add `shm_size: "1gb"` to the Postgres service.
2. Bump version to `0.35.4`.
3. Update changelog/session notes.
4. Validate whitespace locally; compose validation requires Docker.
5. Ask before commit/push.

# Open questions

- None.

# Status

implemented locally; commit/push approval needed.
