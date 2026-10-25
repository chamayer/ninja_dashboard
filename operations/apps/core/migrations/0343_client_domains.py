"""Client domains: learned from computers, editable by operators (ADR-0042).

* Attribute definition ``client.domains`` (text, set, internal): operator
  edits are attribute decisions (add or remove members) through
  ``attribute_decisions.set_attribute_decision``.
* Learned domains are not claims: a claim is one source record's assertion,
  and a client's domains are derived from its computers' records. They are
  computed when read (``apps.core.client_domains``), so nothing writes them.
* ``evaluator_config`` row ``client_domains``: how many live computers must
  report a domain, and the values that are never a client's domain.
"""

from __future__ import annotations

import json
from typing import ClassVar

from django.db import migrations

SETTINGS = {
    "min_computers": 2,
    "ignored": ["", "workgroup", "local", "localdomain", "home", "lan"],
}


def register(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operations.begin_change(
                'attribute_definition.add', 'ADR-0042: client domains.',
                '{"migration": "0343_client_domains"}'::jsonb,
                'migration', NULL, 'operations.migrations', '0343', 1, true)
            """
        )
        cursor.execute(
            """
            INSERT INTO operations.attribute_definitions (
                entity_class_id, key, display_name, description, value_type, cardinality,
                sensitivity, validation, canonical_projection_eligible,
                single_value_conflict_policy, set_merge_policy, definition_version, enabled)
            SELECT 'client', 'domains', 'Domains',
                   'Network domains of this client. Learned from the domains its computers '
                   || 'report; an operator adds or removes them (ADR-0042).',
                   'text', 'set', 'internal', '{}'::jsonb, FALSE,
                   'unknown', 'all_eligible_union', 1, TRUE
             WHERE NOT EXISTS (SELECT 1 FROM operations.attribute_definitions
                                WHERE entity_class_id = 'client' AND key = 'domains')
            """
        )
        cursor.execute(
            """
            INSERT INTO operations.evaluator_config
                (id, tenant_id, evaluator_name, config, updated_at)
            VALUES (gen_random_uuid(), 1, 'client_domains', %s::jsonb, now())
            ON CONFLICT (tenant_id, evaluator_name) DO NOTHING
            """,
            (json.dumps(SETTINGS),),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0342_automatic_client_promotion"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register, migrations.RunPython.noop),
    ]
