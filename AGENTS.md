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
- Remote Python execution must use either a reviewed `.py` file copied to the
  target and invoked by path, or an existing packaged module/management
  command invoked with `python -m`. Never inject Python source through a remote
  command string or standard input. This prohibits `python -c`, `python -`,
  shell pipes or redirection that supply source to Python, and encoded or
  decoded forms such as `exec(bytes.fromhex(...))` and
  `exec(base64.b64decode(...))`. These forms can trigger SentinelOne's Python
  Decode And Execute detection. For SQL-only work, send SQL directly to `psql`.
- The shared `Invoke-DevTool.ps1` SSH helper enforces the invocation shape by
  rejecting recognized Python commands unless they name a `.py` file or use
  `-m module`. This guard applies only when using that helper; it cannot prove
  that a script file was reviewed or copied from a trusted source, and it does
  not control direct SSH or other tools. Review the script before copying it.

Report any check that cannot run locally.

### Local development machine limits

The local development stack (`docker-compose.dev.yml`, the dev Postgres
container and any scratch databases cloned from it) runs on the user's own
workstation. Use it only to check that code works and does not crash: migrations
apply and roll back, functions and triggers behave, a producer or page runs once,
unit tests and small targeted PostgreSQL tests pass.

- Do not run heavy processing locally: full evaluator or reconciliation passes,
  full-fleet rebuilds or backfills, repeated runs for timing, performance or
  before/after baseline comparisons, or anything that holds the database busy for
  minutes. Stop a local run that is still working after a few minutes.
- Exercise a producer on the smallest scope it supports (one device, one client
  or a small synthetic fixture) rather than the whole dataset.
- Keep at most one throwaway scratch database at a time and drop it when the
  check is done; remove temporary Git worktrees and Compose projects you create.
- Measure performance, volume, lock waits and run time only in an authorized
  rehearsal environment or production copy, never on the workstation.

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

Root `BLUEPRINT.md` is an index and cross-service router, not a second plan
document. For Operations work, the detailed active handoff, session history,
and deferred backlog belong in `operations/BLUEPRINT.md`,
`operations/SESSIONS.md`, and `operations/TODO.md`, respectively. Root
`SESSIONS.md` and `TODO.md` receive only concise cross-project pointers when
Operations work affects repository-level status. The plan registry owns plan
status; the linked plan or record owns its durable scope, decisions, and
evidence.

Machine-specific command permissions belong in untracked local tool settings,
not repository instructions.

## Plan-status routing

- `docs/records/PLAN_REGISTRY.md` is the status authority for substantial
  repository plans. Read it before opening nontrivial work.
- Create or update the relevant registry entry before starting a nontrivial
  blueprint, and identify its `PLAN-###` ID in that blueprint.
- Record when each plan was defined, started, and completed; write `—` when a
  lifecycle event has not occurred and state an unknown historical date rather
  than inventing one.
- A plan marked `active` must name the current root or module blueprint;
  `ready` and `verify` plans must retain an explicit resume gate.
- Multiple plans may be active only when their scopes are independent. For
  overlapping scopes, the registry entry must name the related plan and state
  the dependency or execution order before work starts.
- Run `python scripts/validate_plan_registry.py` with the usual documentation
  validation. It is not yet enforced by the governance workflow.

## Blueprint maintenance

- A blueprint is a current resume checkpoint, never a transcript, history, or
  duplicate plan. Keep it at or below 4,000 characters, including headings.
- The root `BLUEPRINT.md` may contain only: (1) a brief repository-wide
  checkpoint, (2) each active plan ID with its status, one next action, and a
  link to its detailed handoff, and (3) cross-service dependencies that cannot
  be understood from those linked sources. Do not put completed-plan
  summaries, implementation narratives, file-by-file detail, test results,
  production evidence, or durable decisions there. Remove a plan's root entry
  when it is complete; the registry retains its status and the plan record
  retains its history and evidence.
- The detailed active handoff belongs in the module blueprint for module work
  (`operations/BLUEPRINT.md` for Operations) or in the designated plan document
  for cross-service work. That source retains goal, scope, affected files,
  steps, decisions, validation, checkpoint, and next action. The plan registry
  owns lifecycle status and dates. `SESSIONS.md` owns chronological history;
  records own durable evidence and audit detail; `TODO.md` or the registered
  backlog owns deferred work. Link to these sources; do not copy their details
  into a blueprint.
- Before starting nontrivial work, identify the correct detailed handoff and
  update it. At milestones and when resuming, reconcile it against Git status,
  diffs, and current files. Before removing duplicated or stale detail, first
  preserve any unique decision, evidence, limitation, or recovery instruction
  in its authoritative source.
- If a blueprint exceeds 4,000 characters, shorten it immediately by routing
  detail to the sources above. Do not keep appending sections or preserve
  completed-plan narratives to avoid losing history; link to the authoritative
  record instead.
