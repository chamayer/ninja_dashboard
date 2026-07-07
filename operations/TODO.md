# Operations TODO

Per `Development/DEVELOPMENT.md`: Inbox / Backlog / Completed. This file is
module-specific; root `../TODO.md` keeps cross-repo items and pointers.

---

## Inbox

- [ ] Review current M0.3-M0.10 WIP diff before committing.
- [ ] Validate Operations container build/start on a Docker-capable host:
      migrations should run as `operations_migrate`, Gunicorn should run with
      `operations_app`, and `/healthz` should pass on `127.0.0.1:8091`.

---

## Backlog

### M0 build

- [ ] M0.11 bootstrap clients from `ninja_core.organizations`.
- [ ] M0.12 brand context/base template/client selector.
- [ ] M0.15 CI and pre-commit configuration.

### Stack-wide (post-M0)

- [ ] TLS reverse proxy in front of the whole stack (postgres/metabase/
      ingest/operations). Options: Caddy (auto-cert, easiest for LAN),
      Traefik (LE via DNS-01), nginx (manual). Currently everything is
      direct-Gunicorn/-Jetty HTTP. Once landed, set `OPERATIONS_HTTPS=1`
      in `.env` and re-enable secure cookies + HSTS. Blueprint §2
      explicitly deferred this; parked here as a conscious "later, not
      never."

### Process

- [ ] Split current uncommitted WIP into approved logical commits:
      auth/tenant foundation, canonical entities, source/collector bindings,
      and independent health/runbook stubs.
- [ ] Tighten `/amr-ch-01_data/ninja-dashboard/.env` permissions to `0640`
      root:docker (currently 0644 world-readable). Coordinate with existing
      ingest/metabase/postgres containers so they can still read it after
      the mode change. Deferred until Operations container is deployed and
      verified, so we change one variable at a time.
- [ ] Audit `/amr-ch-01_data/ninja-dashboard/.env` for values with unquoted
      spaces and add quotes. Discovered when `INGEST_PATCHING_ENABLED_POLICIES`
      broke dash sourcing in the Operations entrypoint (worked around by
      only extracting OPERATIONS_* keys). Bash-based services (postgres,
      metabase) tolerated it; dash didn't. Nice-to-have, not blocking any
      current service.

---

## Completed

- [x] 2026-07-06: Added M0.6 observations, dead-letter table,
      `software_installations_current`, and refresh function migration.
- [x] 2026-07-06: Added M0.7 workflow/audit tables and admin wiring.
- [x] 2026-07-06: Added M0.8 RLS roles, policies, and grants migration.
- [x] 2026-07-06: Added M0.9 tenant/client-scope middleware and helpers.
- [x] 2026-07-06: Added M0.10 seed groups, permissions, taxonomy, and finding types.
- [x] 2026-07-06: Added M0 deployability role split for container startup.
- [x] 2026-07-06: Added module-level Operations build/session/TODO docs.
