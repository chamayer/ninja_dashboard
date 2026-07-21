# Ninja Dashboard development instructions

Ninja Dashboard ingests operational data into Postgres and provides Metabase
dashboards plus the Django-based Operations application.

## Runtime and layout

- Python ingest service under `ingest/`.
- SQL initialization and migrations under `sql/`.
- Metabase dashboards are provisioned by ingest/bootstrap code.
- The Django Operations module is under `operations/` and has more specific
  instructions.
- The stack runs through Docker Compose and is deployed through Portainer.
- Production services are not assumed to run on the development workstation.

## Safety and compatibility

- Treat a push as a production-affecting action. `origin`
  (`chamayer/ninja_dashboard`) is the deployment authority watched by
  Portainer; `a-m-rose/ninja_dashboard` is the required secondary mirror.
  Commit, push, deployment, data rebuild, migration, and rollback actions
  require explicit authorization.
- Obtain separate approval for commit and push, keep commits to one logical
  change, push an approved deployment commit to `origin` before the secondary
  mirror, and report the short commit hash after both pushes.
- Never expose or commit environment values, tokens, customer data, databases,
  generated reports, or local permission settings.
- Preserve schema and dashboard compatibility unless the request explicitly
  authorizes a migration or breaking change.
- For renames, search for the old name across Python, SQL, templates, Compose,
  Dockerfiles, dictionary keys, field lists, migration strings, and dashboard
  bootstrap definitions.
- Check that Dockerfiles include every new runtime file and that Compose
  service definitions still match entrypoints and ports.
- Do not infer production state from local files; verify externally only when
  authorized.

## Planning and continuity

- For nontrivial root-level work, use `.work/plan.md` as the single active plan
  and continuity record.
- Create or update it before implementation with status, goal, scope, affected
  files, steps, decisions, validation plan, checkpoint, and next action.
- Operations-only work uses `operations/.work/plan.md`; the root plan should
  contain only a short pointer when repository-wide coordination is needed.
- Keep plans current while working. A new agent must compare the applicable
  plan with Git status, diffs, and current files before continuing.
- At completion, record actual validation and applicable commit hashes, promote
  durable decisions to `docs/decisions/` or
  `operations/docs/decisions/`, and mark the plan complete.
- Keep active plans tracked for cross-agent continuity. Update them alongside
  related work; do not push a plan-only change merely to trigger a production
  redeploy.
- Do not create an extra commit solely to write that commit's own hash into a
  plan. Record hashes already known and report the pushed hash in the response.
- A completed plan remains until the next nontrivial task in that scope
  replaces it. Git history preserves prior plans.
- Do not use plans as transcripts, chronological histories, or general
  backlogs.
- Put deferred root/cross-service work in `.work/backlog.md`; Operations-only
  deferred work belongs in `operations/.work/backlog.md`.

## Versioning

- The stack uses Semantic Versioning. Root `VERSION` and `CHANGELOG.md` are the
  release authorities, including Operations changes.
- Do not bump the version for exploratory or incomplete work.
- When preparing an approved release, update VERSION and CHANGELOG together.
- Record user-visible and operationally meaningful changes in the changelog.
- Report mismatches between the code, VERSION, and CHANGELOG.

## Validation

Select checks based on the changed area:

- Python syntax/import checks for changed ingest modules.
- Relevant SQL review and migration-order checks.
- Relevant project tests when present.
- Operations-specific checks from `operations/AGENTS.md`.
- `git diff --check` before proposing a commit.
- For approved external or deployment validation, use the workspace helper at
  `..\Scripts\Invoke-DevTool.ps1`; read `docs/operations.md` for safe usage.

Report any check that cannot run locally.

## Definition of done

- The requested behavior is wired through all affected ingest, storage,
  dashboard, or UI layers.
- Relevant validation passes or limitations are explicit.
- Packaging and deployment paths include changed runtime files.
- Release-visible changes update VERSION/CHANGELOG only when preparing an
  approved release.
- Deployment and live data behavior are separately verified when authorized.

## Documentation routing

- Read `README.md` for project setup and primary commands.
- Read `docs/requirements.md` for platform scope and acceptance criteria.
- Read `docs/architecture.md` for ingest, database, Metabase, or service design.
- Read `docs/current-state.md` for the currently supported domains and known
  incomplete areas.
- Read `docs/operations.md` only for deployment, recovery, host, or maintenance
  work.
- Read `operations/AGENTS.md` before changing the Operations module.
- Read `.work/plan.md` when planning, implementing, or resuming active
  root-level work.
- Read `.work/backlog.md` only when selecting or reviewing deferred root work.
- Read `CHANGELOG.md` only when release history is relevant.
