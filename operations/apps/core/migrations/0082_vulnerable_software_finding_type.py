"""Seed the ``vulnerable_software`` FindingType (Software Batch F).

Fires per device when an installed title has a matched CVE that is
either actively exploited (CISA KEV) or severe (CVSS v3 ≥ 7.0).
Severity is set from the worst matched CVE. Auto-resolves when the
title is uninstalled or the operator approves the risk.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


def apply(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    software_cat = FindingCategory.objects.filter(name="software").first()
    FindingType.objects.get_or_create(
        name="vulnerable_software",
        defaults={
            "default_severity": "high",
            "finding_class": "entity",
            "source_module": "platform.software_findings",
            "auto_resolvable": True,
            "runbook_path": "",
            "description": (
                "Installed software has a known vulnerability that is either "
                "actively exploited in the wild (CISA KEV) or scored severe "
                "(CVSS v3 ≥ 7). The vulnerability details are in finding_details."
            ),
            "category": software_cat,
        },
    )


def rollback(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="vulnerable_software").delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0081_software_safety_score_view"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(apply, rollback),
    ]
