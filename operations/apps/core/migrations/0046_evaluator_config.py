"""Migration 0046 — EvaluatorConfig table.

Admin-editable knobs for evaluators. One row per (tenant,
evaluator_name); config JSONB carries the individual keys. First
consumer is the software classifier's rare_recent rule (per operator
request to expose all knobs in an admin page).
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0045_finding_snoozed_until"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluatorConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("evaluator_name", models.CharField(max_length=80)),
                ("config", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("updated_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="evaluator_configs",
                    to=settings.AUTH_USER_MODEL,
                    null=True, blank=True,
                )),
            ],
            options={
                "db_table": "evaluator_config",
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="evaluatorconfig",
            constraint=models.UniqueConstraint(
                fields=("tenant", "evaluator_name"),
                name="uq_evaluator_config_tenant_name",
            ),
        ),
    ]
