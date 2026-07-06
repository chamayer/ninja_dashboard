# Operations

Write-side companion to Metabase in the ninja-dashboard stack.

Read `BLUEPRINT.md` in this directory before making changes. It carries
the settled architecture (Django + DRF + HTMX, tenant-scoped Postgres
with RLS from day one, canonical-entity model, source/collector
separation, finding lifecycle) and the review history behind each
decision.

## Development

Runs inside the ninja-dashboard docker compose stack. Not intended to
run bare on the workstation.

```
docker compose up --build operations
```

- UI + API: <http://localhost:3002>
- Health / internal ops: <http://127.0.0.1:8091/healthz>
- OpenAPI: <http://localhost:3002/api/docs>

Settings modules:

- `config.settings.dev` — workstation development.
- `config.settings.prod` — am-ch-01. Refuses to start without
  `OPERATIONS_SECRET_KEY` and `OPERATIONS_ALLOWED_HOSTS`.

## Layout

```
operations/
├── BLUEPRINT.md          canonical design doc
├── pyproject.toml        deps + tool config
├── manage.py             Django entry point
├── config/               Django project package
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
└── apps/                 first-party Django apps (added per milestone)
```
