"""Migration 0058 — reclassify data-quality FindingTypes as entity.

Correction: `unmatched_source_group` (0.70.0) and
`unnamed_source_group` (0.72.0) were seeded with
`finding_class='admin'`, but per DESIGN §6.1 the admin class is
reserved for findings *about the Operations tool's own health*
(connector down, queue stalled, matview stale, etc.).

These two findings are about **data quality on source records** —
an observation didn't resolve, a source group has no name. They're
operations findings, not admin. Emitter already writes them to
`operations.findings`, which matches the entity class. This migration
just corrects the `finding_class` on the seeded types so the
registry and the emitted rows agree.

No emitter changes, no data migration for existing rows in
`operations.findings` — those rows are already there and correctly
placed.
"""

from __future__ import annotations

from django.db import migrations


_NAMES = ("unmatched_source_group", "unnamed_source_group")


def reclassify_forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name__in=_NAMES).update(finding_class="entity")


def reclassify_reverse(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name__in=_NAMES).update(finding_class="admin")


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0057_placeholder_mac_and_unnamed_source_group"),
    ]

    operations = [
        migrations.RunPython(reclassify_forward, reclassify_reverse),
    ]
