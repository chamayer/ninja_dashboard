"""Migration 0038 — fixup software finding_type rows.

Migration 0037's seed used get_or_create; the 8 software finding types
already existed from a legacy migration with
`source_module='inventory.software'`, so my defaults (category=software,
source_module='platform.software_findings') never applied. Fix in
place: set the category FK and normalize source_module so the
classifier's auto-resolve query matches.
"""

from __future__ import annotations

from django.db import connection, migrations


_SOFTWARE_TYPE_NAMES = [
    "suspicious_name",
    "install_path_suspicious",
    "unauthorized_av",
    "unauthorized_rmm",
    "unauthorized_remote_access",
    "multi_av_conflict",
    "rare_recent",
    "eol_runtime",
]


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE operations.finding_types ft
            SET category_id = fc.id,
                source_module = 'platform.software_findings'
            FROM operations.finding_categories fc
            WHERE fc.name = 'software'
              AND ft.name = ANY(%s)
            """,
            (_SOFTWARE_TYPE_NAMES,),
        )


def rollback(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE operations.finding_types
            SET category_id = NULL,
                source_module = 'inventory.software'
            WHERE name = ANY(%s)
            """,
            (_SOFTWARE_TYPE_NAMES,),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0037_finding_categories_and_software_classifier"),
    ]

    operations = [
        migrations.RunPython(apply, rollback),
    ]
