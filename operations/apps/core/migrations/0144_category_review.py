"""Migration 0144 -- the platform-curator permission for descriptive category.

Same reasoning as 0137's capability permission: category truth is global -- a
product either is a browser or it is not, for every client -- so confirming
one must not be a tenant/client operator right, even though a category can
never raise a finding. Separate permission from `curate_software_capability`
rather than reusing it, matching how `authorize_software_product` (0139) got
its own permission rather than folding into the capability one.

Deliberately no CreateModel for `catalog.category_*`. Those tables are
created by ingest's raw SQL migration 104, which a different container
applies -- same `SeparateDatabaseAndState` hazard 0137 documents for
capability, avoided the same way: Operations reaches these tables through
`apps/core/category.py`, which probes the catalog before every access.
"""

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0143_finding_type_drilldown"),
    ]

    operations: ClassVar[list] = [
        # AlterModelOptions replaces the options dict wholesale, so both the
        # existing capability permission and ordering are restated here;
        # omitting either would silently drop it.
        migrations.AlterModelOptions(
            name="softwarecatalog",
            options={
                "ordering": ("canonical_name",),
                "permissions": (
                    (
                        "curate_software_capability",
                        "Can confirm or reject global software capability claims",
                    ),
                    (
                        "curate_software_category",
                        "Can confirm or reject global software category claims",
                    ),
                ),
            },
        ),
    ]
