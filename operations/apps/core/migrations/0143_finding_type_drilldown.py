"""Register evidence-group drill-through on finding types.

Most device findings lead from a device page to that device's rows in Issues.
Some conditions, such as a usable serial occurring at multiple clients, are a
group whose peer rows are the important review context.  The finding-type
registry owns that behavior: an empty key preserves device scope; a configured
JSON evidence key opens all same-type rows with the same value.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models
from django.db.models import Q


def configure_cross_client_serial(apps, schema_editor):
    apps.get_model("operations", "FindingType").objects.filter(
        name="cross_client_serial"
    ).update(drilldown_evidence_key="serial")


def unconfigure_cross_client_serial(apps, schema_editor):
    apps.get_model("operations", "FindingType").objects.filter(
        name="cross_client_serial"
    ).update(drilldown_evidence_key="")


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0142_shadow_views_readable"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="findingtype",
            name="drilldown_evidence_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Optional finding_details key used for device-page drill-through. "
                    "When empty, the Issues link stays scoped to the selected device; "
                    "when set, it opens all findings of this type with the same "
                    "evidence value."
                ),
                max_length=64,
            ),
        ),
        migrations.AddConstraint(
            model_name="findingtype",
            constraint=models.CheckConstraint(
                condition=(
                    Q(drilldown_evidence_key="")
                    | Q(drilldown_evidence_key__regex=r"^[a-z][a-z0-9_]{0,63}$")
                ),
                name="finding_type_drilldown_evidence_key_format",
            ),
        ),
        migrations.RunPython(configure_cross_client_serial, unconfigure_cross_client_serial),
    ]
