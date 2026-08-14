"""Operations state for the raw product authorization table.

Raw SQL migration 099 creates ``operations.product_authorizations`` because the
ingest classifier consumes it. This migration declares matching Django state
only; the two migration runners start independently and Django must never race
to create a table ingest already owns. Same shape as 0138 for
``platform_product_map`` and 0131 for ``eol_product_map``.

Column parity across the two runners is load-bearing and nothing enforces it,
so ``test_product_authorization_parity`` compares the two definitions.
"""

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0138_capability_policy_identity")]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="ProductAuthorization",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("product_uuid", models.UUIDField()),
                        ("capability", models.CharField(max_length=64)),
                        # No default: permit and deny are opposite decisions and
                        # an authorization must state which one it is.
                        ("polarity", models.BooleanField()),
                        ("rationale", models.TextField()),
                        ("authorized_at", models.DateTimeField(auto_now_add=True)),
                        ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                        ("withdrawn_reason", models.TextField(blank=True, default="")),
                        (
                            "tenant",
                            models.ForeignKey(
                                db_constraint=False,
                                on_delete=models.PROTECT,
                                related_name="product_authorizations",
                                to="operations.tenant",
                            ),
                        ),
                        (
                            "client",
                            models.ForeignKey(
                                blank=True,
                                db_constraint=False,
                                null=True,
                                on_delete=models.PROTECT,
                                related_name="product_authorizations",
                                to="operations.client",
                            ),
                        ),
                        (
                            "authorized_by",
                            models.ForeignKey(
                                db_constraint=False,
                                on_delete=models.PROTECT,
                                related_name="product_authorizations",
                                to="operations.user",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "product_authorizations",
                        "ordering": ("client", "capability", "product_uuid"),
                        "managed": False,
                        "permissions": (
                            (
                                "authorize_software_product",
                                "Can permit or deny a product capability at a client",
                            ),
                        ),
                    },
                ),
            ],
        ),
    ]
