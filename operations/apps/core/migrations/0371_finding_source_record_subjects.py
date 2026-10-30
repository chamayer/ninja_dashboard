"""Finding subject types for native source records and cases (PLAN-004 R4, model state)."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0370_source_record_subjects"),
    ]

    operations: ClassVar[list] = [
        migrations.AlterField(
            model_name="finding",
            name="subject_type",
            field=models.CharField(
                choices=[
                    ("client", "Client"),
                    ("device", "Device"),
                    ("client_user", "Client user"),
                    ("source_binding", "Source binding"),
                    ("collector_instance", "Collector instance"),
                    ("software_product", "Software product"),
                    ("software_version", "Software version"),
                    ("software_installation", "Software installation"),
                    ("source_record", "Source record"),
                    ("source_record_case", "Source record case"),
                ],
                max_length=32,
            ),
        ),
    ]
