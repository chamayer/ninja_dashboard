"""Separate source-record withdrawal from Computer-level review."""

from django.db import migrations


FINDING_NAME = "device_source_record_withdrawn"


def seed(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.update_or_create(
        name=FINDING_NAME,
        defaults={
            "default_severity": "medium",
            "description": "A source record formerly linked to this Computer is withdrawn",
            "finding_class": "entity",
            "source_module": "platform.evaluator",
            "auto_resolvable": True,
            "runbook_path": f"docs/runbooks/{FINDING_NAME}.md",
        },
    )
    FindingType.objects.filter(name="device_missing_from_source").update(
        default_severity="high",
        description="No source currently reports this Computer; operator review required",
        finding_class="entity",
        source_module="platform.evaluator",
        auto_resolvable=True,
        runbook_path="docs/runbooks/device_missing_from_source.md",
    )


def unseed(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name=FINDING_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [("operations", "0155_computer_inventory_source_records")]

    operations = [migrations.RunPython(seed, unseed)]
