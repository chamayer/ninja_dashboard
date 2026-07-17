"""Migration 0045 — Finding.snoozed_until.

Adds a lightweight "snooze until" timestamp so operators can hide a
finding from queues for a chosen window without permanently
suppressing it. The queue view filters snoozed items out until the
timestamp passes.

Wave UI-2.F (Actions) slice 1.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0044_reboot_pending_and_refresh_coordinator"),
    ]

    operations = [
        migrations.AddField(
            model_name="finding",
            name="snoozed_until",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="finding",
            index=models.Index(
                fields=("tenant", "snoozed_until"),
                name="idx_findings_snoozed_until",
            ),
        ),
    ]
