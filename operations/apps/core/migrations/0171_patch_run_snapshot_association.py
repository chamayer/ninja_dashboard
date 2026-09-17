"""Ensure the ingest run log can record the patch cycle snapshot."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0170_grant_software_exposure_condition_reads"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(
            "ALTER TABLE ninja_core.run_log ADD COLUMN IF NOT EXISTS snapshot_at timestamptz;",
            migrations.RunSQL.noop,
        ),
    ]
