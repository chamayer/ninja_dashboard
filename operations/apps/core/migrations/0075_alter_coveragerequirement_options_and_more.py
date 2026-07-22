from __future__ import annotations

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0074_retire_legacy_observations_and_history_maintenance"),
    ]

    operations: ClassVar = [
        migrations.AlterModelOptions(
            name="coveragerequirement",
            options={"ordering": ("entity_type", "platform")},
        ),
        migrations.AlterModelOptions(
            name="queueregistry",
            options={"ordering": ("queue_key",)},
        ),
    ]
