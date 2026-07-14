"""Migration 0030 — sync model state to existing DB column.

The `coverage_requirements.version` column has existed in prod since
migration 0002 (a `VersionedTenantScopedModel` parent that CoverageRequirement
no longer inherited from). The Python model dropped the field, so
Django's ORM stopped writing `version` on INSERT — hitting a NotNull
violation on the first .create() call that ORM'd this table
(surfaced by client_candidate.accept in C3c).

Fix is state-only: re-add the field to the model's Django state so ORM
inserts include it; DB column already exists.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0029_requirement_profiles"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="coveragerequirement",
                    name="version",
                    field=models.PositiveIntegerField(default=1),
                ),
            ],
            database_operations=[],
        ),
    ]
