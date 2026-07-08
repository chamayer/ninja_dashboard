# Operations TODO

Per `Development/DEVELOPMENT.md`: Inbox / Backlog / Completed. This file is
module-specific; root `../TODO.md` keeps cross-repo items and pointers.

---

## Inbox

- [x] After device-list pagination/search ships, live-check
      `/orgs/uta/devices/` through Operations and compare response size/time
      against the previous large render. 2026-07-07: live response was 47,649
      bytes versus the previous 504,547-byte render.
- [x] Validate Operations container build/start on a Docker-capable host:
      migrations should run as `operations_migrate`, Gunicorn should run with
      `operations_app`, and `/healthz` should pass on `127.0.0.1:8091`.
      2026-07-07: confirmed via SSH as `amrose` with plain Docker commands;
      containers healthy, loopback health passed, migrations applied, and
      bootstrap counts populated.

---

## Backlog

### Platform implementation (BLUEPRINT.md — Batches A–E)

Operator action (do before Batch A1 — no code push):
- [ ] Add SOFTWARE_ADDED,SOFTWARE_REMOVED,SOFTWARE_UPDATED to INGEST_ACTIVITY_TYPES_INCLUDE in server .env on am-ch-01

Batch A1 — lifecycle/staleness foundations (Phases 1–2, ship together):
- [x] Phase 1: Django migration 0011 — software_installations_current three-state staleness (fixes active data-loss in refresh function)
- [x] Phase 2: Django migration 0012 — DeviceLink.missing_since + Device/Client lifecycle columns

Batch A2 — finding extensions (Phase 3):
- [x] Phase 3: Django migration 0013 — FindingType extensions + Finding extensions + new finding types

Batch A3 — new platform tables (Phase 4):
- [x] Phase 4: Django migration 0014 — CoverageRequirement, AdminFinding, QueueRegistry, IdentityCandidate, NotificationRule, NotificationState, NotificationEvent + RLS

Batch B — data sync + connectors (Phases 5–7, ship together):
- [x] Phase 5: ingest/core/devices.py — _sync_operations_device_links after _mark_missing_devices
- [x] Phase 6: new package ingest/identity/ — fast_path.py + resolver.py
- [x] Phase 7: Django migration 0015 (S1/SC SourceBindings) + dual-write to entity_observations in ingest.py

Batch C — evaluator + compliance rebuild (Phases 8–10, ship together):
- [x] Phase 8: ingest/evaluator.py — platform evaluator + schedule in main.py
- [x] Phase 9: ingest/agent_compliance/ingest.py — calls platform_evaluate() after AC run
- [x] Phase 10: Django migration 0016 — agent_presence_current materialized view

Batch D — web pages (Phase 11):
- [x] Phase 11: findings review page (/findings/) + admin health page (/admin/findings/health/)

Batch E — naming cleanup (Phases 12–14, coordinate with am-ch-01 .env update):
- [x] Phase 12: docker-compose.yml — rename ninja-ingest → operations-ingest
- [ ] Phase 13: Django migration 0017 — DB role rename ninja_ingest → operations_ingest
- [ ] Phase 14: Django migration 0018 — schema rename ninja_agent_compliance → agent_compliance
- [ ] Repo rename: ninja-dashboard → operations-platform (GitHub rename → local folder mv → Portainer stack git URL update → .claude memory path update). Low risk; GitHub redirects old URLs. Do last.

Operator action (no code push needed):
- [ ] Add SOFTWARE_ADDED,SOFTWARE_REMOVED,SOFTWARE_UPDATED to INGEST_ACTIVITY_TYPES_INCLUDE in server .env on am-ch-01

### M0 build

- [x] Ship server-side pagination/search for per-client device lists.
      Completed in `200c24f`, deployed through `cfa1767`, and live validated.
- [x] Live-validate the committed Operations container through Portainer:
      confirm commit `746770e`, startup migrations/bootstrap, `/healthz`,
      populated clients/devices, and same-password redeploy session
      preservation. 2026-07-07: validated startup health, migrations,
      bootstrap, and data counts. Browser session preservation still needs
      user-facing confirmation after a future redeploy.
- [ ] Browser-confirm Operations admin session survives a same-password
      Portainer redeploy.
- [ ] Decide whether to restore CI/pre-commit after resolving current Ruff
      lint debt, or keep it deferred until tests/lint policy settle.

### Stack-wide (post-M0)

- [ ] Product direction: Operations is the operational data browser and
      control plane, not only an issue-resolution console. Build pages that
      help operators view current canonical data, source evidence, status,
      history, and workflow actions. Keep Metabase for exploratory BI and
      broad historical analytics.
- [ ] Browser-validate fleet overview dashboard. Committed as `8b452f7`,
      deployed via Portainer auto-update. Light browser check pending.
- [ ] Plan next domain browse/detail pages after clients/devices: candidates
      are users, software, sources/collectors, observations/evidence, and
      recent changes.
- [ ] Browser-validate client landing identity coverage section. Committed
      as `a8bf257`, deployed via Portainer auto-update. Light browser
      check pending.
- [x] Client landing identity coverage audit: decide which identities belong
      on the client summary page. Current page shows canonical client plus
      `client_links`; future candidates include source binding health, device
      source coverage, client-user identities, and unlinked external identity
      findings. 2026-07-07: approved as matching Operations' intent; compact
      summary section implemented locally.
- [ ] TLS reverse proxy in front of the whole stack (postgres/metabase/
      ingest/operations). Options: Caddy (auto-cert, easiest for LAN),
      Traefik (LE via DNS-01), nginx (manual). Currently everything is
      direct-Gunicorn/-Jetty HTTP. Once landed, set `OPERATIONS_HTTPS=1`
      in `.env` and re-enable secure cookies + HSTS. Blueprint §2
      explicitly deferred this; parked here as a conscious "later, not
      never."

### Process

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
- [x] 2026-07-06: Added M0.11 bootstrap clients from
      `ninja_core.organizations` (`f13fc9b`).
- [x] 2026-07-06: Added M0.12 brand context, base template, and client
      selector (`aab87da`).
- [x] 2026-07-06: Added and then removed CI/pre-commit while lint policy was
      still unsettled (`1828e90`, `1e3a665`).
- [x] 2026-07-06: Added M1.1 bootstrap devices from `ninja_core.devices`
      (`afee1bf`).
- [x] 2026-07-06: Added device list/detail pages, findings queue, fleet view,
      merge candidates queue, policy editor, and summary sub-pages
      (`c32dae5`..`25584a0`).
- [x] 2026-07-07: Preserved Operations admin sessions across same-password
      redeploys (`746770e`).
