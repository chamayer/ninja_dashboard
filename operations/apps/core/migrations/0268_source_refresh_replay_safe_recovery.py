"""Approve the reviewed source-refresh replay policy."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


EVIDENCE = (
    "A source refresh only reads the configured source API and reconciles local "
    "evidence. Replaying it converges to current source data and performs no "
    "source-side mutation."
)


def approve_source_refresh_recovery(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO operations.job_recovery_policy_authorities
                    (tenant_id, definition_key, recovery_mode, evidence_summary)
                VALUES (1, 'source-refresh', 'replay_safe', %s)
                ON CONFLICT (tenant_id, definition_key) DO NOTHING""",
            [EVIDENCE],
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0267_ensure_reference_sources")
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(approve_source_refresh_recovery, migrations.RunPython.noop)
    ]
