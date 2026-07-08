"""Migration 0018 — agent_presence_current v2: derive client_id from devices JOIN.

The original view (0016) read client_id from entity_observations, which is NULL
for S1/SC/LMI observations because those sources don't carry a client context at
write time. Fix: JOIN operations.devices so client_id is always authoritative.
"""

from __future__ import annotations

from django.db import migrations


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    # Drop and recreate — CONCURRENTLY refresh requires a unique index, which
    # must be rebuilt anyway when the GROUP BY changes.
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
    # refresh function unchanged — REFRESH MATERIALIZED VIEW CONCURRENTLY still works
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
            o.client_id,
            o.device_id,
            o.entity_type,
            o.platform,
            o.subplatform,
            MAX(o.observed_at)  AS last_observed_at,
            MIN(o.observed_at)  AS first_observed_at,
            COUNT(*)            AS observation_count
        FROM operations.entity_observations o
        WHERE o.entity_type LIKE 'agent.%%'
          AND o.device_id IS NOT NULL
        GROUP BY
            o.tenant_id, o.client_id, o.device_id,
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
        ("operations", "0017_ac_migration"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
