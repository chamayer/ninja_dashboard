"""Migration 0053 — identity_conflict FindingType auto_resolvable = True.

Per ADR-0005: the identity_conflict Finding fires when two Devices share
a hostname in the same client without a strong corroborating identifier.
Operator resolution acts on the underlying Devices (merge, retire,
rename) — an entity operation, not a finding-panel action. Once the
underlying condition disappears (only one Device with that hostname
remains), the next resolver drain observes it as resolved.

`auto_resolvable=True` lets the standard finding-close pass sweep the
open Finding away when the condition is gone, matching the entity-action
+ auto-close pattern the rest of the platform uses. The initial seed in
migration 0052 had this set to False, which was inconsistent with how
the finding is actually resolved.
"""

from __future__ import annotations

from django.db import migrations


def flip_auto_resolvable(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="identity_conflict").update(
        auto_resolvable=True,
    )


def unflip_auto_resolvable(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="identity_conflict").update(
        auto_resolvable=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0052_identity_conflict_finding_type"),
    ]

    operations = [
        migrations.RunPython(flip_auto_resolvable, unflip_auto_resolvable),
    ]
