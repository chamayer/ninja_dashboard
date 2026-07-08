"""Migration 0019 — operations.identity_candidates table.

Stores ambiguous identity matches where the async resolver found multiple
devices for the same hostname. Operator reviews and confirms or rejects.
See DESIGN.md §4.4.
"""

from __future__ import annotations

from django.db import migrations


def create_identity_candidates(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE TABLE IF NOT EXISTS operations.identity_candidates (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      BIGINT NOT NULL,
            observation_id UUID REFERENCES operations.entity_observations(observation_id)
                               ON DELETE CASCADE,
            device_id_a    UUID REFERENCES operations.devices(id) ON DELETE CASCADE,
            device_id_b    UUID REFERENCES operations.devices(id) ON DELETE CASCADE,
            confidence     TEXT NOT NULL DEFAULT 'low',
            signals        JSONB NOT NULL DEFAULT '{}',
            status         TEXT NOT NULL DEFAULT 'pending',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at    TIMESTAMPTZ,
            resolved_by    TEXT
        );
        """
    )
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS idx_identity_candidates_tenant_status"
        " ON operations.identity_candidates (tenant_id, status);"
    )
    schema_editor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_candidates_observation
            ON operations.identity_candidates (observation_id)
            WHERE observation_id IS NOT NULL;
        """
    )
    schema_editor.execute(
        "ALTER TABLE operations.identity_candidates OWNER TO operations_migrate;"
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly"):
        schema_editor.execute(
            f"GRANT SELECT, INSERT, UPDATE ON operations.identity_candidates TO {role};"
        )


def drop_identity_candidates(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TABLE IF EXISTS operations.identity_candidates;")


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0018_agent_presence_v2"),
    ]

    operations = [
        migrations.RunPython(create_identity_candidates, drop_identity_candidates),
    ]
