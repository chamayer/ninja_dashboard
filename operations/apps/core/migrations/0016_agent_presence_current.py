"""Migration 0016 — agent_presence_current materialized view.

Aggregates entity_observations WHERE entity_type LIKE 'agent.%' into a
per-device per-platform current-presence summary. Backed by a unique
index so it can be refreshed CONCURRENTLY.

Grants SELECT to operations_app, ninja_ingest, operations_readonly, metabase_ro.
"""

from __future__ import annotations

from django.db import migrations


def create_agent_presence_view(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS operations.agent_presence_current AS
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_presence_pk
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


def drop_agent_presence_view(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS operations.refresh_agent_presence_current();"
    )
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.agent_presence_current;"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0015_seed_s1_sc_lmi_source_bindings"),
    ]

    operations = [
        migrations.RunPython(create_agent_presence_view, drop_agent_presence_view),
    ]
