# Handy Commands

Project reference for the commands that keep coming up in this repo.
Assumes you are on the Docker host `am-ch-01` and the stack is running
under Portainer.

## Ingest

Run a full ingest cycle:

```bash
curl -X POST http://127.0.0.1:8090/run
```

Run the Metabase bootstrap:

```bash
curl -X POST http://127.0.0.1:8090/bootstrap-metabase
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
