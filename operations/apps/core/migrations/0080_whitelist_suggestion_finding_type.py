"""Seed the ``whitelist_suggestion`` FindingType (Software Batch 3).

Fires for titles that are uncategorised, undecided at every scope, and
installed on ≥ N devices. Threshold + severity are tunable via
``EvaluatorConfig``. The suggestion surfaces in the standard findings
queue and the software decisions queue — one row per (device × title),
same aggregation pattern as other software finding types.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


def apply(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    software_cat = FindingCategory.objects.filter(name="software").first()
    FindingType.objects.get_or_create(
        name="whitelist_suggestion",
        defaults={
            "default_severity": "low",
            "finding_class": "entity",
            "source_module": "platform.software_findings",
            "auto_resolvable": True,
            "runbook_path": "",
            "description": (
                "Software installed on ≥ N devices fleet-wide with no "
                "categorisation and no operator decision — a candidate to "
                "approve as a fleet whitelist or reject explicitly."
            ),
            "category": software_cat,
        },
    )


def rollback(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="whitelist_suggestion").delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0079_software_decision_publisher_scope"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(apply, rollback),
    ]
