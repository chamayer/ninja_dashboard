"""Operations state for the raw capability policy map, plus scope repair.

Raw SQL migration 095 creates ``operations.platform_product_map`` because the
ingest classifier consumes it. This migration declares matching Django state
only; the two migration runners start independently and Django must never race
to create a table ingest already owns.

It also repairs the pre-capability unauthorized finding scope. Policy is per
client, so an unauthorized result is a device fact. A product-scoped result
cannot represent one client allowing a product while another forbids it.
Existing open product-scoped rows are closed and will be regenerated at the
correct scope when capability enforcement is explicitly enabled.
"""

from typing import ClassVar

from django.db import migrations, models
from django.utils import timezone


def repair_unauthorized_scope(apps, schema_editor):
    Finding = apps.get_model("operations", "Finding")
    FindingType = apps.get_model("operations", "FindingType")
    names = ("unauthorized_av", "unauthorized_rmm", "unauthorized_remote_access")
    types = FindingType.objects.filter(name__in=names)
    types.update(subject_scope="device", creates_device_exposure=True)
    Finding.objects.filter(
        finding_type__name__in=names,
        subject_type="software_product",
        status__in=("open", "acknowledged"),
    ).update(status="resolved", closed_at=timezone.now())


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0137_capability_review")]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="PlatformProductMap",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("product_uuid", models.UUIDField()),
                        ("capability", models.CharField(max_length=64)),
                        ("component_role", models.CharField(default="agent", max_length=16)),
                        ("provenance", models.TextField()),
                        ("enabled", models.BooleanField(default=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "agent",
                            models.ForeignKey(
                                db_constraint=False,
                                on_delete=models.PROTECT,
                                related_name="product_capability_maps",
                                to="operations.agent",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "platform_product_map",
                        "ordering": ("agent", "capability", "component_role"),
                        "managed": False,
                    },
                ),
            ],
        ),
        migrations.RunPython(repair_unauthorized_scope, migrations.RunPython.noop),
    ]
