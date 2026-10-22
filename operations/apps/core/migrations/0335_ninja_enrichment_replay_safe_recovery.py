"""Approve replay-safe recovery for the read-only Ninja enrichment Job."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

PATCHES_EVIDENCE = (
    "The Ninja patch/activity collector reads the vendor API and reconciles local "
    "domain projections. A later replay converges to current source state and "
    "has no vendor-side mutation."
)
NINJA_ENRICHMENT_EVIDENCE = (
    "The Ninja enrichment collector reads health, policy, custom-field, and "
    "location endpoints and writes local evidence only. A later replay converges "
    "to current source state and has no vendor-side mutation."
)


def approve_ninja_enrichment_recovery(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO operations.job_recovery_policy_authorities
                    (tenant_id, definition_key, recovery_mode, evidence_summary)
                VALUES
                    (1, 'patches', 'replay_safe', %s),
                    (1, 'ninja-enrichment', 'replay_safe', %s)
                ON CONFLICT (tenant_id, definition_key) DO UPDATE
                   SET recovery_mode = EXCLUDED.recovery_mode,
                       evidence_summary = EXCLUDED.evidence_summary,
                       reviewed_at = now()""",
            [PATCHES_EVIDENCE, NINJA_ENRICHMENT_EVIDENCE],
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0334_safe_observation_identity_metadata"),
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(approve_ninja_enrichment_recovery, migrations.RunPython.noop)
    ]
