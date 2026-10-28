# PLAN-028 — Local production configuration parity

## Goal

Allow local Operations and ingest to use production-equivalent source,
feature, and notification configuration while keeping the local database and
local credentials isolated and all scheduled Jobs disabled.

## Scope

- Use `.env.dev` for production-equivalent non-database settings and
  integrations, loaded only by local Compose.
- Keep Postgres/Operations/Metabase database credentials, local host settings,
  Django secret, and local admin password unchanged.
- Keep scheduled Jobs disabled. Manual collection and notification jobs may
  still call configured production source or notification endpoints.
- Do not copy source data or credentials automatically; provide a local
  PowerShell merge procedure. No production reads, writes, commits, or pushes.

## Affected files

- `docker-compose.dev.yml`
- `README.md`
- `docs/records/PLAN_REGISTRY.md`, `BLUEPRINT.md`

## Decisions and validation

Preserve local database and admin settings when importing prod configuration;
replace matching non-local variables instead of appending duplicate keys.
Compose forces `SCHEDULED_JOBS_ENABLED=false`. Removing Compose's notification
overrides makes `.env.dev` notification settings effective, so manual Jobs can
send to live endpoints. Compose rendering and plan registry validation pass;
`git diff --check` passes with only existing line-ending warnings. No source
collection or notification job ran.

## Checkpoint

Completed 2026-10-28. Compose uses local env settings for notifications and
keeps scheduled Jobs disabled. The user's env merge initially produced CRLF;
the local file was normalized to LF without printing or changing values, then
app services were recreated. Operations is healthy, login and Django checks
pass, the Jobs worker reports ready with its unused HTTP health probe disabled,
and the ingest schedule gate is false. No source or notification jobs ran.

## Next action

Configure local bindings and manually run sources/jobs when ready. Future
PowerShell env merges must preserve LF line endings.
