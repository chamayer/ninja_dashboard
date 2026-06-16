# Handy Commands

Project reference for the commands that keep coming up in this repo.
Assumes you are on the Docker host `am-ch-01` and the stack is running
under Portainer.

## Deploy

Pull the latest code on the Docker host:

```bash
cd /amr-ch-01_data/ninja-dashboard && git pull
```

Rebuild and restart ingest:

```bash
cd /amr-ch-01_data/ninja-dashboard && docker compose build ingest && docker compose up -d ingest
```

Check running container port binding:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep ninja-ingest
```

## Ingest

Run a full ingest cycle:

```bash
curl -X POST http://127.0.0.1:8090/run
```

Run patching ingest only:

```bash
curl -fsS -X POST http://127.0.0.1:8090/run/patches
```

Run the Metabase bootstrap:

```bash
curl -X POST http://127.0.0.1:8090/bootstrap-metabase
```

Check ingest liveness:

```bash
curl -fsS http://127.0.0.1:8090/healthz
```

Check ingest readiness:

```bash
curl -fsS http://127.0.0.1:8090/readyz
```

## Agent Compliance

Run a full Agent Compliance collection. This calls Ninja, SentinelOne,
LogMeIn, and ScreenConnect, then evaluates compliance and dispatches
first-time notifications if alerting is enabled:

```bash
curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance
```

Run Agent Compliance evaluate-only. This does not call vendor APIs; it
rebuilds the current compliance model from the latest stored
observations, applies current customer/alias/config rules, and dispatches
first-time notifications if alerting is enabled:

```bash
curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance-evaluate
```

Check recent Agent Compliance runs:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT domain,status,rows_upserted,rows_inserted,started_at,finished_at,error_text FROM ninja_core.run_log WHERE domain LIKE 'agent_compliance%' ORDER BY started_at DESC LIMIT 10;"
```

Check Agent Compliance source health:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT platform,source_name,status,rows_observed,LEFT(COALESCE(error_text,''),160) AS error_text FROM ninja_agent_compliance.v_source_health_current ORDER BY platform,source_name;"
```

Check current device work queue:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT work_state,COUNT(*) FROM ninja_agent_compliance.v_device_work_queue GROUP BY work_state ORDER BY COUNT(*) DESC;"
```

Check devices to fix:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT COUNT(*) AS devices_to_fix FROM ninja_agent_compliance.v_device_work_queue WHERE work_state IN ('Fix now','Review');"
```

Check notification readiness:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT ready_to_notify,notification_status,COUNT(*) FROM ninja_agent_compliance.v_notification_queue GROUP BY ready_to_notify,notification_status ORDER BY ready_to_notify DESC,COUNT(*) DESC;"
```

Check customer-name review queue:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT candidate_name,platform,current_devices,suggested_customer,review_reason FROM ninja_agent_compliance.v_customer_name_queue ORDER BY current_devices DESC,candidate_name LIMIT 50;"
```

Check customer mapping status:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT overall_status,COUNT(*) FROM ninja_agent_compliance.v_org_alignment_current GROUP BY overall_status ORDER BY COUNT(*) DESC;"
```

Check latest Agent Compliance migration:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT version,applied_at FROM ninja_core.schema_migrations WHERE version LIKE '%agent_compliance%' ORDER BY applied_at DESC LIMIT 10;"
```

Watch Agent Compliance logs:

```bash
docker logs --tail 150 ninja-ingest | awk '/agent compliance|Agent compliance|Dashboard ready|ERROR|Traceback/ {print}'
```

Verify the current dashboard wording migration:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT version,applied_at FROM ninja_core.schema_migrations WHERE version = '040_agent_compliance_online_in_wording';"
```

Check the current custom-field allowlist seen by the running container:

```bash
docker exec -it ninja-ingest printenv INGEST_CUSTOM_FIELDS_INCLUDE
docker exec -it ninja-ingest python -c "from ingest.config import settings; print(settings.INGEST_CUSTOM_FIELDS_INCLUDE)"
```

Backfill historical activities (all codes in the current allowlist):

```bash
docker exec ninja-ingest python -m ingest.activities.backfill --days 90
```

Backfill ONE or a FEW specific activity statusCode(s) only — useful
after adding a new code to the allowlist when you don't want to re-walk
the whole history for every code. The `-e` override wins because the
ingest config loads `/app/.env` with `override=False`, so process env
takes precedence. Comma-separated for multiple codes:

```bash
docker exec -e INGEST_ACTIVITY_TYPES_INCLUDE=SOFTWARE_PATCH_MANAGEMENT_MESSAGE ninja-ingest python -m ingest.activities.backfill --days 90
```

Delete activity rows whose `activity_type` is no longer in the
allowlist (cleanup after tightening the filter). Refreshes the
dependent rollup MV:

```bash
docker exec -i ninja-postgres psql -U ninja -d ninja -c "DELETE FROM ninja_activities.activities WHERE activity_type NOT IN ('PATCH_MANAGEMENT_APPLY_PATCH_STARTED','PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED','PATCH_MANAGEMENT_MESSAGE','PATCH_MANAGEMENT_FAILURE','PATCH_MANAGEMENT_ROLLBACK_PATCH_REQUESTED','PATCH_MANAGEMENT_ROLLBACK_PATCH_STARTED','PATCH_MANAGEMENT_ROLLBACK_PATCH_COMPLETED','PATCH_MANAGEMENT_PATCH_APPROVED','PATCH_MANAGEMENT_PATCH_REJECTED','PATCH_MANAGEMENT_SCAN_COMPLETED','SOFTWARE_PATCH_MANAGEMENT_SCAN_STARTED','SOFTWARE_PATCH_MANAGEMENT_MESSAGE','SYSTEM_REBOOTED'); REFRESH MATERIALIZED VIEW ninja_activities.device_activity_signal;"
```

## Logs

Tail ingest logs:

```bash
docker logs --tail=200 -f ninja-ingest
```

Tail Metabase logs:

```bash
docker logs --tail=200 -f ninja-metabase
```

Tail Postgres logs:

```bash
docker logs --tail=200 -f ninja-postgres
```

## Postgres

Open a SQL shell:

```bash
docker exec -it ninja-postgres psql -U ninja -d ninja
```

## Agent Compliance

Run collection:

```bash
curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance
```

Run evaluation only:

```bash
curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance-evaluate
```

Refresh Metabase cards:

```bash
curl -fsS -X POST http://127.0.0.1:8090/bootstrap-metabase
```

Check applied device-state migration:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT version, applied_at FROM ninja_core.schema_migrations WHERE version = '047_agent_compliance_device_state_model';"
```

Check device state counts:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT device_state, COUNT(*) FROM ninja_agent_compliance.v_device_state_current GROUP BY device_state ORDER BY COUNT(*) DESC;"
```

Check work queue state counts:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT work_state, COUNT(*) FROM ninja_agent_compliance.v_device_work_queue GROUP BY work_state ORDER BY COUNT(*) DESC;"
```

Check platform-level drilldown rows for one device:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT client_name, hostname, platform, required, found, platform_status, age_text, platform_customer, platform_hostname, notes FROM ninja_agent_compliance.v_device_platform_detail_current WHERE hostname = '<DEVICE_NAME>' ORDER BY client_name, hostname, platform;"
```

Check cross-customer review decisions:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT decision_type, client_id, norm_name, platform, hostname, notes, created_at FROM ninja_agent_compliance.v_human_decisions_current ORDER BY created_at DESC LIMIT 50;"
```

Clear the custom-field ingest table before a clean re-ingest:

```bash
docker exec -it ninja-postgres psql -U ninja -d ninja -c "TRUNCATE ninja_core.custom_field_values;"
```

## Metabase SQL

Open Metabase in the browser and use:

`+ New` -> `SQL query`

Useful queries:

Devices grouped by patching scope:

```sql
SELECT
  COALESCE(d.patching_scope, 'Unknown') AS "Patching Scope",
  COUNT(*) AS device_count
FROM ninja_core.v_active_devices d
GROUP BY 1
ORDER BY 2 DESC, 1;
```

Custom-field names with unique values and counts:

```sql
SELECT
  field_name,
  COALESCE(
    value_text,
    value_number::text,
    value_bool::text,
    '[null]'
  ) AS field_value,
  COUNT(*) AS value_count
FROM ninja_core.custom_field_values
GROUP BY 1, 2
ORDER BY 1, 3 DESC, 2;
```

Check one device in the active view:

```sql
SELECT
  id,
  system_name,
  patching_disabled,
  patching_scope,
  patching_notes,
  organization_id
FROM ninja_core.v_active_devices
WHERE id = 6801;
```

Check the raw custom-field rows for a device and its org:

```sql
SELECT
  entity_type,
  entity_id,
  field_name,
  value_bool,
  value_text,
  last_observed_at
FROM ninja_core.custom_field_values
WHERE entity_id IN (6801, 3)
  AND field_name IN (
    'patchingDisabled',
    'serverPatchingDisabled',
    'workstationPatchingDisabled',
    'patchingNotes'
  )
ORDER BY entity_type, entity_id, field_name, last_observed_at DESC;
```

## Probes

Probe custom-field values:

```bash
docker exec -it ninja-ingest python -m ingest.probe /queries/scoped-custom-fields --pages 1 --page-size 20 --param "scopes=NODE,ORGANIZATION" --param "fields=patchingDisabled,serverPatchingDisabled,workstationPatchingDisabled,patchingNotes" --full
```

Scan field names and sample values:

```bash
docker exec -it ninja-ingest python -m ingest.probe_fields --records 200 --page-size 100 --preview 40
```

## Notes

- The ingest container loads `/app/.env` once at startup. If you edit
  the host `.env`, recreate the container or redeploy the stack so it
  rereads the file.
- The stack publishes ingest only on `127.0.0.1:8090`; use the Docker
  host or an SSH tunnel from your workstation.
