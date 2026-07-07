# Goal

Complete M0 remaining slices: CI + pre-commit, bootstrap clients from
`ninja_core.organizations`, brand/template/client-selector scaffold.

# Why

M0.3–M0.10 + deploy plumbing are shipped, verified running on am-ch-01
against the ninja-dashboard stack (commits `5d0456a`..`3ad38d0`). Three
build slices remain to close M0: M0.15 (CI safety net), M0.11 (real
client data), M0.12 (brand/template/selector).

# Scope

Order: M0.15 → M0.11 → M0.12.

- **M0.15 — CI + pre-commit** (this slice, active).
  - `.github/workflows/ci.yml` — ruff + Django check + makemigrations
    --check --dry-run on push / PR.
  - `.pre-commit-config.yaml` — ruff, ruff-format, EOF/whitespace,
    check-added-large-files, check-yaml.
  - No production code changes.
- **M0.11 — Bootstrap clients** (next).
  - Managed=False model against `ninja_core.organizations`.
  - Management command `bootstrap_clients_from_ninja` — idempotent
    upsert of Client + ClientLink(source=Ninja).
  - Runs as `operations_migrate` (bypasses RLS).
- **M0.12 — Brand + templates + client selector** (after M0.11).
  - `operations.context_processors.brand`.
  - `templates/base.html` scaffold.
  - Header client selector reading `Client.objects` in tenant 1.
  - `/orgs/all/` and `/orgs/<slug>/` URL rewrites via existing
    `ClientScopeMiddleware`.

Out of scope for now: real UI views, ingest endpoint, HTTPS
(explicitly parked in backlog).

# Files to change (M0.15 only, this slice)

- `.github/workflows/ci.yml` — new, workflow definition.
- `.pre-commit-config.yaml` — new, hook config.
- `operations/BUILD_BLUEPRINT.md` — this file (already updated).
- `operations/SESSIONS.md` — add session entry when M0.15 lands.
- `operations/TODO.md` — move M0.15 from Backlog to Completed on commit.

# Steps

1. Write `.pre-commit-config.yaml` at repo root — ruff check, ruff
   format, standard hygiene hooks.
2. Write `.github/workflows/ci.yml` — Ubuntu, Python 3.12, install
   dev deps, `ruff check`, `python operations/manage.py check`,
   `python operations/manage.py makemigrations --check --dry-run`.
3. Commit + push (branch: master, per user's no-branches workflow).
4. Verify: check GitHub Actions tab for green build on push.
5. Update SESSIONS.md + TODO.md.

# Open questions

- Whether to also run pytest in CI. Punt: no tests yet in the tree.
  Add pytest step later when tests land.
- Whether to gate merges on CI passing. Punt: user is solo on master;
  green is aspirational not enforced.

# Status

M0.15 planning. Awaiting approval to write CI files.
