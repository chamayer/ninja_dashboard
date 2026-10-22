"""Add the resolver's "renamed at source" client candidate status (ADR-0038).

Choices only: ``client_candidates.status`` has no database constraint, so
this changes Django state and runs no SQL.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0336_jobs_ninja_enrichment_resource_limit")
    ]

    operations: ClassVar[list] = [
        migrations.AlterField(
            model_name="clientcandidate",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("accepted", "Accepted"),
                    ("mapped", "Mapped"),
                    ("excluded", "Excluded"),
                    ("renamed", "Renamed at source"),
                ],
                default="open",
                max_length=16,
            ),
        ),
    ]
