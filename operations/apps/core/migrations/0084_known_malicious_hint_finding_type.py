"""Seed the ``known_malicious_hint`` FindingType (Software Batch H).

Fires per device when the installed title accumulates ``>= N`` open
threat-intel signals (title-scope or matched publisher-scope) and has
no operator approval decision on record. Explicitly a **hint**, not
proof — OSINT is community-curated and noisy — so severity defaults
to low and the tuning knobs live on ``EvaluatorConfig``.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


def apply(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    software_cat = FindingCategory.objects.filter(name="software").first()
    FindingType.objects.get_or_create(
        name="known_malicious_hint",
        defaults={
            "default_severity": "low",
            "finding_class": "entity",
            "source_module": "platform.software_findings",
            "auto_resolvable": True,
            "runbook_path": "",
            "description": (
                "Community threat-intel feeds (OTX, MalwareBazaar, ThreatFox) "
                "report signals about this title or its publisher. Review "
                "and either approve, reject, or investigate — a positive "
                "hint is not proof of compromise."
            ),
            "category": software_cat,
        },
    )


def rollback(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="known_malicious_hint").delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0083_software_safety_score_unknown_band"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(apply, rollback),
    ]
