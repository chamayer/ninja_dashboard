"""Report missing source-role configuration at its platform scope."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

CONDITION = "source_record_policy_incomplete"


def register_platform_condition(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE operations.finding_types
               SET finding_class = 'admin',
                   source_module = 'ingest.platform_findings', subject_scope = 'device',
                   allowed_subject_kinds = ARRAY[]::text[], auto_resolvable = TRUE,
                   display_name = 'Source record role policy is missing',
                   issue_category = 'Data collection',
                   issue_group = 'Collection and processing'
             WHERE name = %s
            """,
            (CONDITION,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("source_record_policy_incomplete finding type is missing")


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0384_source_record_mac_validation"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_platform_condition, migrations.RunPython.noop),
    ]
