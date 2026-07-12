"""Migration 0026 — seed the duplicate_platform_record admin finding type.

Hostname correlation is cross-source only: two records of the same
(platform, entity_type) stream with the same hostname stay separate
device rows (each consumes a license) and the evaluator raises this
finding for the group.
"""

from __future__ import annotations

from django.db import migrations


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        INSERT INTO operations.finding_types
            (name, default_severity, finding_class, source_module,
             auto_resolvable, runbook_path, description)
        VALUES
            ('duplicate_platform_record', 'high', 'admin', 'evaluator', TRUE, '',
             'Multiple records of the same platform stream share one hostname '
             'within a client — likely duplicate agents, each consuming a license.')
        ON CONFLICT (name) DO NOTHING;
        """
    )


def downgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DELETE FROM operations.finding_types WHERE name = 'duplicate_platform_record';"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0025_presence_all_entities"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
