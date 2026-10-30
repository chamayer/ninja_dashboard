"""Expose condition_namespace on the Finding model (PLAN-003 R2 follow-up).

The column exists since 0363. This is a model-state change only: the default
``Finding.objects`` manager now returns entity-namespace rows, so readers keep
the population they had before admin findings joined the ledger in 0364.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0368_publish_findings_contract_4"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="finding",
                    name="condition_namespace",
                    field=models.CharField(default="entity", editable=False, max_length=16),
                ),
                migrations.AlterModelOptions(
                    name="finding",
                    options={"base_manager_name": "all_namespaces"},
                ),
                migrations.AlterModelManagers(
                    name="finding",
                    managers=[
                        ("objects", models.Manager()),
                        ("all_namespaces", models.Manager()),
                    ],
                ),
            ],
        ),
    ]
