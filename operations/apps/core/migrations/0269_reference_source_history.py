"""Carry verified reference-feed history into source-managed presentation."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


LEGACY_JOB_KEYS = {
    "reference.nvd": "intel-nvd",
    "reference.cpe": "intel-cpe-dict",
    "reference.kev": "intel-kev",
    "reference.epss": "intel-epss",
    "reference.otx": "intel-otx",
    "reference.abusech": "intel-abusech",
    "reference.winget": "intel-winget",
    "reference.chocolatey": "intel-chocolatey",
    "reference.remote-access": "intel-lolrmm",
    "reference.end-of-life": "intel-endoflife",
}


def preserve_reference_history(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for source_key, job_key in LEGACY_JOB_KEYS.items():
            cursor.execute(
                """
                UPDATE operations.source_instances
                   SET config = COALESCE(config, '{}'::jsonb)
                                || jsonb_build_object('legacy_job_key', %s)
                 WHERE config->>'source_key' = %s
                """,
                [job_key, source_key],
            )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0268_source_refresh_replay_safe_recovery")
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(preserve_reference_history, migrations.RunPython.noop)
    ]
