"""Migration 0021 — agent_presence_current: add device_type column.

Adds d.device_type to the materialized view so coverage queries can scope
present-count and total by device_scope ('server' / 'workstation' / 'all')
without a separate JOIN to operations.devices at query time.

device_id → device_type is a functional dependency, so the existing unique
index on (tenant_id, device_id, entity_type, platform) still holds.
"""

from __future__ import annotations

from django.db import migrations


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.agent_presence_current;"
    )
    schema_editor.execute(
        """
        CREATE MATERIALIZED VIEW operations.agent_presence_current AS
        SELECT
            o.tenant_id,
            d.client_id,
            o.device_id,
            d.device_type,
            o.entity_type,
            o.platform,
            o.subplatform,
            MAX(o.observed_at)  AS last_observed_at,
            MIN(o.observed_at)  AS first_observed_at,
            COUNT(*)            AS observation_count
        FROM operations.entity_observations o
        JOIN operations.devices d
          ON d.id = o.device_id
         AND d.deleted_at IS NULL
        WHERE o.entity_type LIKE 'agent.%%'
          AND o.device_id IS NOT NULL
        GROUP BY
            o.tenant_id, d.client_id, o.device_id, d.device_type,
            o.entity_type, o.platform, o.subplatform
        WITH DATA;
        """
    )
    schema_editor.execute(
        """
        CREATE UNIQUE INDEX idx_agent_presence_pk
            ON operations.agent_presence_current (tenant_id, device_id, entity_type, platform);
        """
    )
    schema_editor.execute(
        """
        CREATE INDEX idx_agent_presence_client
            ON operations.agent_presence_current (tenant_id, client_id, platform, device_type);
        """
    )
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION operations.refresh_agent_presence_current()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY operations.agent_presence_current;
        END;
        $$;
        """
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly", "metabase_ro"):
        schema_editor.execute(
            f"GRANT SELECT ON operations.agent_presence_current TO {role};"
        )
    schema_editor.execute(
        "ALTER MATERIALIZED VIEW operations.agent_presence_current OWNER TO operations_migrate;"
    )


def downgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.agent_presence_current;"
    )
    schema_editor.execute(
        """
        CREATE MATERIALIZED VIEW operations.agent_presence_current AS
        SELECT
            o.tenant_id,
            d.client_id,
            o.device_id,
            o.entity_type,
            o.platform,
            o.subplatform,
            MAX(o.observed_at)  AS last_observed_at,
            MIN(o.observed_at)  AS first_observed_at,
            COUNT(*)            AS observation_count
        FROM operations.entity_observations o
        JOIN operations.devices d
          ON d.id = o.device_id
         AND d.deleted_at IS NULL
        WHERE o.entity_type LIKE 'agent.%%'
          AND o.device_id IS NOT NULL
        GROUP BY
            o.tenant_id, d.client_id, o.device_id,
            o.entity_type, o.platform, o.subplatform
        WITH DATA;
        """
    )
    schema_editor.execute(
        """
        CREATE UNIQUE INDEX idx_agent_presence_pk
            ON operations.agent_presence_current (tenant_id, device_id, entity_type, platform);
        """
    )
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION operations.refresh_agent_presence_current()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY operations.agent_presence_current;
        END;
        $$;
        """
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly", "metabase_ro"):
        schema_editor.execute(
            f"GRANT SELECT ON operations.agent_presence_current TO {role};"
        )
    schema_editor.execute(
        "ALTER MATERIALIZED VIEW operations.agent_presence_current OWNER TO operations_migrate;"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0020_source_run_queue"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
