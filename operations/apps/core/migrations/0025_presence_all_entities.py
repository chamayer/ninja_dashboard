"""Migration 0025 — agent_presence_current covers every entity stream.

Track E: the matview previously filtered `entity_type LIKE 'agent.%'`,
hiding vm.guest / vm.host / network.device / monitor.target presence.
Now every non-software stream is present, and `last_contact_at` carries
platform truth (canonical_data->>'last_seen_at') so lifecycle and
offline logic run on the platform's clock, not our fetch time.

Also seeds the 'unmapped_node_class' admin finding type — unmapped Ninja
node_classes are surfaced, never silently dropped.
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

_LEGACY_VIEW_BODY = """
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


def _rebuild(schema_editor, body: str) -> None:
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.agent_presence_current;"
    )
    schema_editor.execute(body)
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


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _rebuild(schema_editor, _VIEW_BODY)
    schema_editor.execute(
        """
        INSERT INTO operations.finding_types
            (name, default_severity, finding_class, source_module,
             auto_resolvable, runbook_path, description)
        VALUES
            ('unmapped_node_class', 'medium', 'admin', 'evaluator', TRUE, '',
             'Ninja records whose node_class has no entity_type mapping — '
             'observed as unknown and awaiting a mapping decision.')
        ON CONFLICT (name) DO NOTHING;
        """
    )


def downgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _rebuild(schema_editor, _LEGACY_VIEW_BODY)


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0024_track_e_identity_model"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
