# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Define v1 of an agent-compliance extension inside `ninja-dashboard`:
continuous collection across Ninja, SentinelOne, LogMeIn, and multiple
per-client ScreenConnect instances, with per-client platform
requirements, a basic dashboard, and alerting.

## Why

The existing PowerShell script proves the operational need but is a
manual/report-oriented workflow. The platform already has the right
building blocks: scheduled Python ingest, Postgres, migrations, run
logging, and Metabase dashboards. Keeping v1 inside `ninja-dashboard`
avoids duplicating Postgres/Metabase while still adding cross-platform
agent compliance as a separate domain.

## Scope

**In for v1:**
- Collect all four platform families:
  - Ninja: shared multi-client source.
  - SentinelOne: shared multi-client source.
  - LogMeIn Central: shared multi-client source.
  - ScreenConnect: many per-client tenant sources, each with its own
    credentials.
- DB-backed non-secret config:
  - clients
  - platform sources
  - client aliases
  - per-client platform requirements
  - stale thresholds
  - alert rules
  - suppressions
- Secrets remain in host `.env`, referenced from DB config by secret
  name.
- Build a current compliance matrix per client + normalized hostname.
- Add basic Metabase dashboard cards/tables.
- Add alert evaluation with dedupe/cooldown state and webhook delivery.

**Out for v1:**
- Full polished config admin UI.
- Direct secret editing in the web UI.
- Automated remediation.
- Client-facing access.
- Advanced rule language beyond the first supported finding types.
- Separate Postgres or separate Metabase stack.

## Files to Change

- `AGENT_COMPLIANCE_PROPOSAL.md` — durable proposal and v1 scope.
- `TODO.md` — backlog entry so the project does not disappear when
  this blueprint is overwritten.

Future implementation files, not part of this planning-only pass:
- `sql/migrations/017_agent_compliance.sql`
- `ingest/agent_compliance/`
- `ingest/main.py`
- `ingest/config.py`
- `.env.example`
- `ingest/metabase_bootstrap.py`

## Steps

1. Capture the v1 proposal in `AGENT_COMPLIANCE_PROPOSAL.md`.
2. Update this `BLUEPRINT.md` with the agreed implementation boundary.
3. Add a `TODO.md` backlog item for the agent-compliance domain.
4. Wait for approval before implementation.

## Open Questions

- Alert destination for v1: Teams webhook, Slack webhook, generic
  webhook, SMTP, or more than one?
- Should ScreenConnect wrong-tenant detection be alerting in v1 or
  dashboard-only at first?
- Should the first config source be seeded by SQL migration only, or
  loaded from a YAML bootstrap file into DB tables?
- Should agent-compliance run on the same schedule as patch ingest or
  have its own `AGENT_COMPLIANCE_SCHEDULE_HOURS`?

## Status

implemented — Python compile passed; migration/live DB smoke pending
