"""Operations state for data-backed serial quality and cross-client review.

Raw SQL migration 102 owns the identity-value rejection table because ingest
uses it in the fast path. Django declares state only so Operations can edit the
explicit rejection catalog without racing the raw migration runner.

`cross_client_serial` is deliberately separate from `shared_serial`: the
latter is a same-client duplicate group, while this is a per-device review
finding for a usable serial that appears under more than one client. Neither is
an instruction to merge devices.
"""

from typing import ClassVar

from django.db import migrations, models

_FINDING = {
    "name": "cross_client_serial",
    "default_severity": "high",
    "source_module": "identity.resolver",
    "description": (
        "This device has a usable canonical serial also reported by one or more "
        "other clients. It may be a cross-client ownership or source-attribution "
        "conflict. Review the affected devices; this finding never merges them."
    ),
}


def add_finding_type(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    category = FindingCategory.objects.filter(name="identity").first()
    FindingType.objects.update_or_create(
        name=_FINDING["name"],
        defaults={
            "default_severity": _FINDING["default_severity"],
            "finding_class": "entity",
            "source_module": _FINDING["source_module"],
            "description": _FINDING["description"],
            "category": category,
            "subject_scope": "device",
            "creates_device_exposure": False,
            "suppressed_by_approval": False,
            "auto_resolvable": True,
        },
    )


def remove_finding_type(apps, schema_editor):
    apps.get_model("operations", "FindingType").objects.filter(
        name=_FINDING["name"]
    ).delete()


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0139_product_authorizations"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="IdentityValueRejection",
                    fields=[
                        ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                        ("value_kind", models.CharField(max_length=32)),
                        ("normalized_value", models.CharField(max_length=255)),
                        ("reason", models.TextField()),
                        ("enabled", models.BooleanField(default=True)),
                        ("provenance", models.TextField(default="operations_admin")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "identity_value_rejections",
                        "managed": False,
                        "ordering": ("value_kind", "normalized_value"),
                    },
                ),
            ],
        ),
        migrations.RunPython(add_finding_type, remove_finding_type),
    ]
