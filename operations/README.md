# Operations

Write-side companion to Metabase in the ninja-dashboard stack.

Read `AGENTS.md` before making changes. Use `docs/architecture.md` as the
concise guide and `DESIGN.md` as the detailed architecture authority during
the documentation transition. `BLUEPRINT.md` contains mixed implemented and
pending planning material; active work belongs in `.work/plan.md`.

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
├── AGENTS.md             standing development instructions
├── DESIGN.md             detailed architecture authority during transition
├── docs/                 concise references, decisions, and runbooks
├── .work/plan.md         active implementation checkpoint
├── BLUEPRINT.md          mixed historical and pending planning source
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
