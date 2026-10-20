# Ninja Dashboard development instructions

Ninja Dashboard ingests operational data into Postgres and provides the
Django-based Operations application.

## Runtime and layout

- Python ingest service under `ingest/`.
- SQL initialization and migrations under `sql/`.
- The Django Operations module is under `operations/` and has more specific
  instructions.
- The stack runs through Docker Compose and is deployed through Portainer.
- Production services are not assumed to run on the development workstation.

## Language and style

- Use American English in project documentation, plans, decision records,
  comments, user-facing copy, and development communication unless quoting an
  external source verbatim.

## Safety and compatibility

- Treat a push as a production-affecting action. `origin`
  (`chamayer/ninja_dashboard`) is the deployment authority watched by
  Portainer; `a-m-rose/ninja_dashboard` is the required secondary mirror.
  An approved `origin` push automatically triggers the Portainer deployment;
  do not trigger a separate redeploy. The push approval includes that automatic
  deployment, and service startup applies pending ingest and Django migrations,
  so the approval must explicitly include the reviewed pending migrations. A
  standalone redeploy not coupled to an approved push, manual migration, data
  rebuild, rollback, and other production changes still require their own
  explicit authorization.
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
- Read `docs/README.md` when locating the correct documentation authority.
- Use `docs/reference/` for durable external or vendor development reference
  material; it is neither runtime input nor archival history.
- Use `docs/records/` for retained maintenance records and audit summaries.
- Read `docs/requirements.md` for platform scope and acceptance criteria.
- Read `docs/architecture.md` for ingest, database, or service design.
- Read `docs/current-state.md` for the currently supported domains and known
  incomplete areas only after checking its status date.
- Read `docs/operations.md` only for deployment, recovery, host, or maintenance
  work.
- Read `operations/AGENTS.md` before changing the Operations module.
- Read `CHANGELOG.md` only when release history is relevant.

## Module work-state routing

For Operations work, root `BLUEPRINT.md` is the cross-service checkpoint and
router. The detailed active handoff, session history, and deferred backlog are
respectively `operations/BLUEPRINT.md`, `operations/SESSIONS.md`, and
`operations/TODO.md`. Root `SESSIONS.md` and `TODO.md` receive only concise
cross-project pointers when Operations work affects repository-level status.

Machine-specific command permissions belong in untracked local tool settings,
not repository instructions.
