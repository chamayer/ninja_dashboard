"""Use clear operator wording for the Computer-level source-loss finding."""

from django.db import migrations


def update_label(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="device_missing_from_source").update(
        description="No sources currently report this Computer; operator review required"
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0156_source_withdrawal_review_findings")]

    operations = [migrations.RunPython(update_label, migrations.RunPython.noop)]
