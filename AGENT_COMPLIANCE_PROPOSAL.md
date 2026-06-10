# Agent Compliance Proposal

## Summary

Add agent compliance as a new domain inside `ninja-dashboard`.

The goal is to continuously collect device presence/status from Ninja,
SentinelOne, LogMeIn Central, and one or more per-client
ScreenConnect tenants, then evaluate each client against its own
required platform combo. v1 includes collection, DB-backed config,
a basic Metabase dashboard, and webhook/email/Zendesk alerting.

This should not become a separate full stack in v1. It should reuse
the existing Postgres, Metabase, scheduler, migration pattern, and
Portainer deployment model.

## Platform Model

Shared multi-client sources:
- Ninja
- SentinelOne
- LogMeIn Central

Per-client sources:
- ScreenConnect

ScreenConnect is different because each client may have its own
ScreenConnect tenant and credentials. A device should only satisfy a
client's ScreenConnect requirement when it appears in that client's
configured ScreenConnect source.

## V1 Architecture

```text
Ninja / SentinelOne / LogMeIn / ScreenConnect tenants
        |
        v
ingest agent_compliance module
        |
        v
Postgres: config + observations + compliance matrix + alert state
        |
        v
Metabase dashboard + alert delivery
```

The implementation should live under a new domain:

```text
ingest/agent_compliance/
```

Suggested module layout:

```text
ingest/agent_compliance/
  __init__.py
  ingest.py
  config_loader.py
  normalize.py
  alerts.py
  clients/
    ninja.py
    sentinelone.py
    logmein.py
    screenconnect.py
```

## Configuration

Use Postgres for operational config, not `.env`.

DB-backed config should include:
- clients
- platform sources
- client aliases
- required platform combos
- stale thresholds
- alert rules
- alert suppressions
- notification routes

Keep secrets out of ordinary DB tables. Store secret references in the
DB and keep actual values in the host `.env`.

Example:

```text
platform_sources:
  source_name: UTA ScreenConnect
  platform: ScreenConnect
  client_name: UTA
  base_url: https://utaw.screenconnect.com
  ext_guid_secret_ref: SC_UTA_EXT_GUID
  secret_key_secret_ref: SC_UTA_SECRET_KEY
```

Actual values remain in `/amr-ch-01_data/ninja-dashboard/.env`:

```env
SC_UTA_EXT_GUID=...
SC_UTA_SECRET_KEY=...
```

## Per-Client Requirements

Each client can define required platforms by device scope.

Example:

```text
Default:
  all: Ninja + SentinelOne + LogMeIn

UTA:
  workstation: Ninja + ScreenConnect + SentinelOne
  server: Ninja + SentinelOne + LogMeIn

A.M. Rose:
  all: Ninja + LogMeIn

C2P:
  all: Ninja + SentinelOne
```

The collector records observations. The compliance matrix evaluates
whether each client/device satisfies the configured requirements.

## Proposed Database Objects

Schema:

```sql
ninja_agent_compliance
```

Core config tables:
- `clients`
- `platform_sources`
- `client_aliases`
- `platform_requirements`
- `alert_rules`
- `alert_suppressions`
- `notification_routes`

Observation and result tables:
- `source_runs`
- `platform_observations`
- `compliance_matrix_current`
- `compliance_matrix_history`
- `compliance_findings`
- `alert_events`
- `alert_state`

Observation rows should include:
- `observed_at`
- `platform`
- `source_id`
- `source_name`
- `source_client_name`
- `resolved_client_name`
- `hostname`
- `norm_name`
- `device_id`
- `is_online`
- `last_seen_at`
- `device_type`
- `os_name`
- `raw_data jsonb`

Compliance matrix rows should include:
- `client_name`
- `hostname`
- `norm_name`
- `device_type`
- `required_platforms`
- `observed_platforms`
- `missing_required_platforms`
- `stale_required_platforms`
- `unknown_required_platforms`
- `source_failed_platforms`
- `is_compliant`
- `is_stale`
- `is_unknown`
- `cross_client_conflict`
- `finding_signature`

## Collection

Default v1 cadence:

```env
AGENT_COMPLIANCE_ENABLED=true
AGENT_COMPLIANCE_SCHEDULE_HOURS=4
```

Collection sequence:
1. Load enabled platform sources from DB.
2. Resolve secret references from environment.
3. Fetch shared sources: Ninja, SentinelOne, LogMeIn.
4. Fetch every enabled ScreenConnect tenant.
5. Normalize hostnames.
6. Resolve each observation to a client using aliases and source
   ownership.
7. Write observations.
8. Build current compliance matrix.
9. Evaluate findings.
10. Send alerts for new or changed findings.

## Basic Dashboard

Add a Metabase dashboard:

```text
Ninja - Agent Compliance
```

V1 cards:
- Compliance %
- Noncompliant devices
- Missing SentinelOne
- Missing ScreenConnect
- Missing LogMeIn
- Stale devices
- Cross-client conflicts
- Active alert findings

V1 tables:
- Current compliance matrix
- Remediation candidates
- Missing required platforms by client
- Cross-client or wrong-tenant conflicts
- Recent alert events

Filters:
- Client
- Device type
- Missing platform
- Finding type
- Severity

## Alerting

Alerting is in scope for v1.

Delivery starts with generic webhook, SMTP email, and Zendesk request
routes. Routes are DB-configured; credentials and target secrets stay
in `.env`.

Environment:

```env
AGENT_COMPLIANCE_ALERTS_ENABLED=true
AGENT_COMPLIANCE_ALERT_WEBHOOK_URL=
AGENT_COMPLIANCE_ALERT_COOLDOWN_HOURS=24
AGENT_COMPLIANCE_ALERT_EMAIL_TO=
AGENT_COMPLIANCE_SMTP_HOST=
AGENT_COMPLIANCE_ZENDESK_URL=
AGENT_COMPLIANCE_ZENDESK_REQUESTER_EMAIL=
```

V1 finding types:
- Missing required platform.
- Required platform stale beyond client threshold.
- Cross-client hostname conflict.
- ScreenConnect wrong-tenant conflict.
- Collector/source failure.

Alert dedupe key:

```text
client_name + norm_name + finding_type + missing_platforms + expected_source_id
```

Alert behavior:
- Send immediately for new findings.
- Do not resend unchanged findings until cooldown expires.
- Send changed findings when severity or missing platform combo changes.
- Mark findings resolved when they disappear.
- Keep append-only `alert_events` history.

Suggested severities:
- Missing SentinelOne: critical.
- Missing Ninja: critical.
- Server missing required remote access: high.
- Workstation missing ScreenConnect: high or medium by client.
- Stale all required platforms: high.
- Cross-client/wrong-tenant conflict: high.
- Single stale non-security platform: medium.

## V1 Implementation Phases

1. Add schema and config tables.
2. Seed initial client/source/requirement config.
3. Port collectors from the PowerShell script.
4. Build normalization and client resolution.
5. Build compliance matrix.
6. Add alert rules, state, and webhook/email/Zendesk delivery.
7. Add basic Metabase dashboard.
8. Run side-by-side with the PowerShell report for validation.
9. Rotate exposed credentials after Python ingest is proven.

## Implemented V1 Shape

Implemented files:
- `sql/migrations/019_agent_compliance.sql`
- `ingest/agent_compliance/`
- `ingest/agent_compliance/clients/`
- `ingest/agent_compliance/metabase_bootstrap.py`

Runtime behavior:
- Ninja observations are derived from existing `ninja_core` tables.
- SentinelOne, LogMeIn, and ScreenConnect observations come from their
  native APIs.
- Source failures become source-health findings and suppress missing
  platform evaluation for that failed source.
- Alert delivery supports webhook, SMTP email, and Zendesk requests.
- Agent compliance has its own scheduler and manual endpoint.

Manual run:

```bash
curl -X POST http://127.0.0.1:8090/run/agent-compliance
```

Ninja `/queries/device-health` exposes AV/security enrichment such as
product installation status and threat counts. That data is useful
triage context for S1 findings, but SentinelOne API remains the
authoritative S1 compliance source.

## Decisions

- Keep this inside `ninja-dashboard` for v1.
- Do not duplicate Postgres or Metabase.
- Treat ScreenConnect as many per-client sources.
- Store operational config in Postgres.
- Store only secret references in DB; actual secrets stay in `.env`.
- Include alerting in v1, starting with webhook, email, and Zendesk
  request delivery.
- Defer admin UI until the config model is proven.

## Risks

- Hostname matching can create false positives if clients reuse naming
  conventions. Cross-client conflict reporting must be visible from
  the start.
- ScreenConnect tenant mapping must be explicit; do not infer tenant
  ownership from hostname alone.
- Alert spam is likely without dedupe/cooldown state, so alert state is
  required in v1.
- API rate limits and vendor failures should create source-health
  findings, not silent gaps.
