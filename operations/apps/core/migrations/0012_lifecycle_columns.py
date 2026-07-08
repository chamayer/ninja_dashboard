"""Migration 0012 — universal lifecycle columns.

Adds to DeviceLink: missing_since
Adds to Device:     created_at, created_reason, updated_at, updated_reason,
                    stale_since, stale_reason, deleted_reason
Adds to Client:     same 7 columns as Device
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0011_software_staleness"),
    ]

    operations = [
        # ── DeviceLink ────────────────────────────────────────────────
        migrations.AddField(
            model_name="devicelink",
            name="missing_since",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ── Device ────────────────────────────────────────────────────
        migrations.AddField(
            model_name="device",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="device",
            name="created_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="device",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="device",
            name="updated_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="device",
            name="stale_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="device",
            name="stale_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="device",
            name="deleted_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),

        # ── Client ────────────────────────────────────────────────────
        migrations.AddField(
            model_name="client",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="client",
            name="created_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="client",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="client",
            name="updated_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="client",
            name="stale_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="stale_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="client",
            name="deleted_reason",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
