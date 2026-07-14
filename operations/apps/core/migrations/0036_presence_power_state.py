"""Migration 0036 — agent_presence_current gains last_power_state.

For vm.guest / vm.host rows the hypervisor's `power_state` is the
authoritative signal of whether the device is currently alive. It
wasn't projected into the matview, so consumers had no way to tell a
running VM from a powered-off one without joining raw observations.
Adds a `last_power_state` column (most-recent value per row's group)
via array_agg-ordered-desc.

Also rebuilds indexes + refresh function + grants (matview drop is
required to change the column list).
"""

from __future__ import annotations

from django.db import migrations


_VIEW_BODY = """
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
    MAX((o.canonical_data ->> 'last_seen_at')::timestamptz) AS last_contact_at,
    (ARRAY_AGG(o.canonical_data ->> 'power_state' ORDER BY o.observed_at DESC))[1]
        AS last_power_state,
    COUNT(*)            AS observation_count
FROM operations.entity_observations o
JOIN operations.devices d
  ON d.id = o.device_id
 AND d.deleted_at IS NULL
WHERE o.device_id IS NOT NULL
  AND o.entity_type <> 'software'
GROUP BY
    o.tenant_id, d.client_id, o.device_id, d.device_type,
    o.entity_type, o.platform, o.subplatform
WITH DATA;
"""


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.agent_presence_current;"
    )
    schema_editor.execute(_VIEW_BODY)
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
    # First refresh cannot use CONCURRENTLY (index just created).
    schema_editor.execute(
        "REFRESH MATERIALIZED VIEW operations.agent_presence_current;"
    )


def downgrade(apps, schema_editor):
    # No downgrade — rolling forward is cheap; rolling back would drop
    # the column but leave callers broken.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0035_device_offline_generalization"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
