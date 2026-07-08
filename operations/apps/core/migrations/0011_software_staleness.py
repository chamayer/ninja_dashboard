"""Migration 0011 — software_installations_current three-state staleness.

Replaces the hard-DELETE in refresh_software_installations_current() with a
stale/unmark pattern:
  stale_since = NULL       → current
  stale_since = <ts>       → stale (absent from latest run)
  deleted_at  = <ts>       → tombstone (operator or expiry)

The DELETE step is removed; rows are never auto-deleted.
"""

from django.db import migrations


def upgrade_software_staleness(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        ALTER TABLE operations.software_installations_current
            ADD COLUMN IF NOT EXISTS stale_since    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS stale_reason   TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS deleted_at     TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS deleted_reason TEXT NOT NULL DEFAULT '';
        """
    )

    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION operations.refresh_software_installations_current(
            p_tenant_id bigint DEFAULT NULL
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = operations, pg_temp
        AS $$
        BEGIN
            -- Step 1: upsert from entity_observations (unchanged logic)
            WITH latest AS (
                SELECT DISTINCT ON
                    (tenant_id, client_id, device_id, entity_key)
                    tenant_id,
                    client_id,
                    device_id,
                    entity_key AS canonical_name,
                    raw_data ->> 'publisher'   AS publisher,
                    raw_data ->> 'version'     AS version,
                    raw_data ->> 'location'    AS install_location,
                    NULLIF(raw_data ->> 'installDate', '')::date AS install_date,
                    MIN(observed_at) OVER (
                        PARTITION BY tenant_id, client_id, device_id, entity_key
                    ) AS first_observed_at,
                    observed_at AS last_observed_at
                FROM operations.entity_observations
                WHERE entity_type = 'software'
                  AND client_id IS NOT NULL
                  AND device_id IS NOT NULL
                  AND (p_tenant_id IS NULL OR tenant_id = p_tenant_id)
                ORDER BY tenant_id, client_id, device_id, entity_key,
                         observed_at DESC
            )
            INSERT INTO operations.software_installations_current AS t
                (tenant_id, client_id, device_id, canonical_name,
                 publisher, version, install_location, install_date,
                 first_observed_at, last_observed_at, refreshed_at)
            SELECT tenant_id, client_id, device_id, canonical_name,
                   publisher, version, install_location, install_date,
                   first_observed_at, last_observed_at, now()
              FROM latest
            ON CONFLICT (tenant_id, client_id, device_id, canonical_name)
            DO UPDATE SET
                publisher         = EXCLUDED.publisher,
                version           = EXCLUDED.version,
                install_location  = EXCLUDED.install_location,
                install_date      = EXCLUDED.install_date,
                first_observed_at = LEAST(t.first_observed_at, EXCLUDED.first_observed_at),
                last_observed_at  = GREATEST(t.last_observed_at, EXCLUDED.last_observed_at),
                refreshed_at      = now(),
                stale_since       = NULL,
                stale_reason      = '';

            -- Step 2: mark rows stale where no current observation exists
            UPDATE operations.software_installations_current t
            SET stale_since  = now(),
                stale_reason = 'ninja.ingest.observation_missing'
            WHERE (p_tenant_id IS NULL OR t.tenant_id = p_tenant_id)
              AND t.stale_since IS NULL
              AND t.deleted_at  IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM operations.entity_observations o
                  WHERE o.entity_type = 'software'
                    AND o.tenant_id   = t.tenant_id
                    AND o.client_id   = t.client_id
                    AND o.device_id   = t.device_id
                    AND o.entity_key  = t.canonical_name
              );

            -- Step 3: unmark stale where observation reappeared
            -- (handled by ON CONFLICT DO UPDATE above — stale_since set to NULL there)
        END;
        $$;
        """
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0010_seed_ninja_source_binding"),
    ]

    operations = [
        migrations.RunPython(upgrade_software_staleness, migrations.RunPython.noop),
    ]
