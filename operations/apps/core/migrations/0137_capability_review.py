"""Migration 0137 -- Operations side of capability recognition.

Three things, none of them DDL against the capability tables themselves:

1. **The platform-curator permission.** Capability truth is global -- a product
   either is remote-access software or it is not, for every client. So
   confirming one must not be a tenant/client operator right. This permission
   is separate from the ordinary software-decision rights and defaults to
   nobody, exactly as the restricted-evidence reveal permission in 0117 does.

2. **The review finding type**, registered but with a disabled emitter. Phase 1
   is shadow mode: candidate evidence records assertions and raises nothing.
   The registry row exists now so the surfaces and routes can be built and
   reviewed against a real type rather than a placeholder.
   `suppressed_by_approval` is FALSE: capability truth and software trust are
   different questions. Approving software as allowed must not suppress a
   request to confirm what the product actually is.

3. Deliberately **no CreateModel for catalog.capability_***. Those tables are
   created by ingest's raw SQL migration 093, which a different container
   applies. Declaring them to Django's state here with
   `SeparateDatabaseAndState` would let the admin read them, but it would also
   assert a column list that nothing keeps in step -- migration 0131 records
   exactly that hazard for `eol_product_map` ("column parity ... is deliberate
   and load-bearing, since nothing enforces it across the two migration
   runners"). Operations reaches these tables through
   `apps/core/capability.py`, which probes the catalog before every access, so
   a missing 093 degrades instead of raising.
"""

from typing import ClassVar

from django.db import migrations

_REVIEW_FINDING = {
    "name": "capability_review_candidate",
    "default_severity": "low",
    "source_module": "platform.capability_match",
    "description": (
        "Candidate capability evidence needs review: a publisher rule or "
        "community tag suggests this product is endpoint-security, RMM or "
        "remote-access software, but no vetted identity or operator has "
        "confirmed it. Confirming or rejecting records a global capability "
        "assertion; it does not decide whether the software is allowed here, "
        "which stays a software decision."
    ),
}


def add_finding_type(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    # Production's finding-type sequence predates several data-managed registry
    # inserts and can lag the table's maximum id.  Synchronize it before this
    # migration inserts the review type; otherwise an otherwise-idempotent
    # update_or_create retries the same duplicate primary key on every startup.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('operations.finding_types', 'id'),
                COALESCE((SELECT max(id) FROM operations.finding_types), 1),
                EXISTS (SELECT 1 FROM operations.finding_types)
            )
            """
        )
    category = FindingCategory.objects.filter(name="software").first()
    FindingType.objects.update_or_create(
        name=_REVIEW_FINDING["name"],
        defaults={
            "default_severity": _REVIEW_FINDING["default_severity"],
            "source_module": _REVIEW_FINDING["source_module"],
            "description": _REVIEW_FINDING["description"],
            "category": category,
            # A capability claim is about the product, not any device running
            # it, so it must not fan out across installations.
            "subject_scope": "software_product",
            "creates_device_exposure": False,
            "suppressed_by_approval": False,
            "auto_resolvable": True,
        },
    )


def remove_finding_type(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name=_REVIEW_FINDING["name"]).delete()


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0136_finding_type_suppressed_by_approval"),
    ]

    operations: ClassVar[list] = [
        # AlterModelOptions replaces the options dict wholesale, so `ordering`
        # is restated here; omitting it would silently drop it.
        migrations.AlterModelOptions(
            name="softwarecatalog",
            options={
                "ordering": ("canonical_name",),
                "permissions": (
                    (
                        "curate_software_capability",
                        "Can confirm or reject global software capability claims",
                    ),
                ),
            },
        ),
        migrations.RunPython(add_finding_type, remove_finding_type),
    ]
