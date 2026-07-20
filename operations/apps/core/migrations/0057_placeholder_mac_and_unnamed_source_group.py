"""Migration 0057 — seed two more data-quality FindingTypes.

Follow-through on the "nothing hidden" audit
(`operations/docs/nothing-hidden-audit.md`). Two remaining silent
filters that the 0.70.0 arc didn't cover:

- **`placeholder_mac`** — `ingest/normalize.py::_JUNK_MACS` (all-zero,
  all-FF, VirtualBox default NAT) are silently disregarded from MAC-
  based identity correlation. Analogous to `placeholder_serial`.
- **`unnamed_source_group`** — `ingest/identity/client_resolver.py:104`
  silently skips source groups (e.g. LMI "-1" placeholders) that
  arrive with an empty name/normalized_name. Never reaches the
  `unmatched_source_group` path.

Emission is wired into the resolver + client_resolver in a companion
code change; this migration only seeds the types.
"""

from __future__ import annotations

from django.db import migrations


_SEEDS = [
    (
        "placeholder_mac",
        "medium",
        "entity",
        "identity",
        "identity.resolver",
        True,
        "Device is reporting a placeholder / filler MAC address "
        "('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff', or the "
        "VirtualBox default '02:00:4c:4f:4f:50') among its network "
        "interfaces. The resolver correctly ignores such MACs for "
        "identity correlation; this finding surfaces the affected "
        "devices so operators can correct or acknowledge the data "
        "quality gap.",
    ),
    (
        "unnamed_source_group",
        "low",
        "admin",
        "identity",
        "identity.client_resolver",
        True,
        "A source published an org/group observation with an empty "
        "name (e.g., LogMeIn '-1' placeholder groups). The resolver "
        "silently skipped these before this finding shipped; now "
        "they surface per (source_binding, entity_key) so operators "
        "can decide whether to fix at source, add to "
        "placeholder_org_names, or ignore.",
    ),
]


def seed_more_data_quality_types(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")

    for name, severity, klass, category_name, source_module, auto, description in _SEEDS:
        category = FindingCategory.objects.filter(name=category_name).first()
        FindingType.objects.update_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "finding_class": klass,
                "category": category,
                "source_module": source_module,
                "auto_resolvable": auto,
                "description": description,
            },
        )


def unseed_more_data_quality_types(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(
        name__in=[name for name, *_ in _SEEDS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0056_data_quality_finding_types"),
    ]

    operations = [
        migrations.RunPython(seed_more_data_quality_types, unseed_more_data_quality_types),
    ]
