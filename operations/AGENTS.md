# Operations module development instructions

Operations is the Django, DRF, and HTMX control-plane application within the
Ninja Dashboard stack.

## Runtime and layout

- Python 3.12.
- Django 5.1, DRF, HTMX, psycopg, and Postgres.
- Application code is under `apps/`; project configuration is under `config/`.
- Templates are under `templates/`.
- Migrations are part of application behavior and require explicit review.
- The module normally runs in the repository's Docker Compose stack.

## Architectural constraints

- `docs/architecture.md` is the concise architecture guide.
- During the documentation transition, `DESIGN.md` remains the detailed
  architecture authority. Report any conflict between it, the concise guide,
  BLUEPRINT, and implemented behavior rather than silently choosing a winner.
- Preserve tenant scoping and row-level security from the first query through
  the rendered response.
- Runtime ORM checks may return misleading results without tenant context.
- Canonical entities, observations, derived state, operator decisions, and
  effective views have distinct responsibilities; do not collapse them without
  an approved architecture decision.
- Source-specific collectors must not become platform-wide authorities.
- ADR-0012 states the entity model these rules derive from. Non-negotiable:
  a source assertion is evidence, never state; no evidence producer
  (connector, resolver, evaluator, UI action) writes a source-derived value
  directly — only the shared projector does, however rarely it changes;
  a relationship may carry its own attributes, with no volume exemption;
  ownership determines scope, and an unscoped entity never references a
  scoped one.
- State a rule with its enforcement mechanism or not at all. Prose without a
  privilege, constraint, registry row, or test is a description, and this
  repository has repeatedly shipped inert ones.
- Use `docs/glossary.md` vocabulary. "Layer", "canonical", "effective",
  "asset", "authority" and "type" each mean several things historically; the
  glossary records which.
- Do not reintroduce dependencies on legacy agent-compliance code or schemas
  when a native Operations path exists.
- Canonical entities are not automatically deleted because a source stops
  reporting them.

## Safety

- Schema changes, data rebuilds, queue manipulation, RLS changes, credential
  handling, deployment, commit, and push require explicit authorization. In
  the current GitOps path, an approved `origin` push triggers deployment and
  the Operations entrypoint automatically applies pending Django migrations;
  the push approval must explicitly include both effects. Manual migration or
  redeploy remains separately authorized.
- Never place live credentials or customer data in documentation, fixtures,
  tests, or local databases.
- Treat ignored local databases and `.claude/settings.local.json` as
  machine-specific artifacts.
- Review old-name references across Python, templates, migrations, SQL,
  entrypoints, and documentation after any model or field rename.
- In PostgreSQL scripts, do not rely on `psql -v` substitution inside
  `DO $$...$$`; use an appropriate supported mechanism such as `\gexec` or
  `current_setting()` for the specific task.

## Planning and continuity

- For nontrivial Operations work, use `operations/.work/plan.md` as the single
  active implementation plan and continuity record.
- Create or update it before implementation with status, goal, scope, affected
  files, steps, decisions, validation plan, checkpoint, and next action.
- Keep it current during implementation and verify it against Git status,
  diffs, migrations, and current files when resuming.
- At completion, record actual validation and applicable commit hashes, promote
  durable reasoning to `operations/docs/decisions/`, and mark the plan
  complete.
- Keep the Operations plan tracked for cross-agent continuity and update it
  alongside related code. Do not push a plan-only change merely to trigger a
  production redeploy.
- Do not create an extra commit solely to place that commit's own hash in the
  plan. Record hashes already known and report the pushed hash in the response.
- A completed Operations plan remains until the next nontrivial Operations task
  replaces it.
- Put deferred Operations work in `operations/.work/backlog.md` with sufficient
  paths, constraints, risk, and revisit criteria.
- Stack releases still use the root `VERSION` and `CHANGELOG.md`; do not create
  an independent module version unless explicitly approved.

## Validation

Use the relevant subset:

- `python manage.py check`
- `ruff check .`
- `ruff format --check .`
- Targeted `pytest` tests
- Template loading or focused request smoke checks
- Migration-plan review for schema changes
- For approved external or deployed-stack validation, use the workspace helper
  at `..\..\Scripts\Invoke-DevTool.ps1`; read `docs/operations.md` and the root
  `docs/operations.md` for safe usage.

Run these in the documented project environment. Do not claim workstation
validation when the required services or dependencies are unavailable.

## Definition of done

- Tenant and RLS behavior remains correct.
- The implementation follows the current architecture authorities.
- Relevant checks pass or limitations are documented.
- Migrations and deployment packaging are complete when applicable.
- The active plan records current work and reasoning, not a session transcript.

## Documentation routing

- Read `README.md` for module entry points and setup.
- Read `docs/decisions/0012-entity-model-foundations.md` and
  `docs/glossary.md` before any entity, attribute, relationship, or scope
  work — they are short and prevent the terminology collisions that have
  repeatedly cost time.
- Read `docs/architecture.md` first for data model, identity, queue, finding,
  or platform changes, then consult `DESIGN.md` for detailed rules.
- Read `docs/requirements.md` for parity and acceptance questions.
- Read `docs/operations.md` for deployment, RLS verification, recovery, or
  maintenance.
- Read `docs/runbooks/<topic>.md` only for the matching operational condition.
- Read `.work/plan.md` when planning, implementing, or resuming the active
  Operations task.
- Read `.work/backlog.md` only when selecting or reviewing deferred Operations
  work.
- Read decision records when changing a previously settled architectural rule.
