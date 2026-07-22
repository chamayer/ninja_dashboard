from django.db import migrations


SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_software_installations_current(
    p_tenant_id bigint DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $$
BEGIN
    WITH latest AS (
        SELECT DISTINCT ON (tenant_id, client_id, device_id, entity_key)
               tenant_id, client_id, device_id, entity_key AS canonical_name,
               canonical_data ->> 'publisher' AS publisher,
               canonical_data ->> 'version' AS version,
               canonical_data ->> 'location' AS install_location,
               NULLIF(canonical_data ->> 'install_date', '')::date AS install_date,
               observed_at AS last_observed_at
          FROM operations.entity_observation_current
         WHERE entity_type = 'software' AND active
           AND client_id IS NOT NULL AND device_id IS NOT NULL
           AND (p_tenant_id IS NULL OR tenant_id = p_tenant_id)
         ORDER BY tenant_id, client_id, device_id, entity_key, observed_at DESC
    )
    INSERT INTO operations.software_installations_current AS t
      (tenant_id, client_id, device_id, canonical_name, publisher, version,
       install_location, install_date, first_observed_at, last_observed_at,
       refreshed_at)
    SELECT tenant_id, client_id, device_id, canonical_name, publisher, version,
           install_location, install_date, last_observed_at, last_observed_at,
           now()
      FROM latest
    ON CONFLICT (tenant_id, client_id, device_id, canonical_name)
    DO UPDATE SET publisher = EXCLUDED.publisher, version = EXCLUDED.version,
      install_location = EXCLUDED.install_location, install_date = EXCLUDED.install_date,
      last_observed_at = EXCLUDED.last_observed_at, refreshed_at = now(),
      stale_since = NULL, stale_reason = '';

    UPDATE operations.software_installations_current t
       SET stale_since = now(), stale_reason = 'ninja.ingest.observation_missing'
     WHERE (p_tenant_id IS NULL OR t.tenant_id = p_tenant_id)
       AND t.stale_since IS NULL AND t.deleted_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM operations.entity_observation_current o
            WHERE o.entity_type = 'software' AND o.active
              AND o.tenant_id = t.tenant_id AND o.client_id = t.client_id
              AND o.device_id = t.device_id AND o.entity_key = t.canonical_name
       );
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0067_alter_coveragerequirement_options_and_more")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
