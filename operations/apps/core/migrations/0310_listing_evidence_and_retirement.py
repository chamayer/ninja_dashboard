"""What lists a Computer, and what is evidence that it exists (ADR-0032).

* Record lifecycles ``documentation`` and ``stopped``, with mapping rows: a
  current (not archived) Hudu asset is documentation, a powered-off or
  suspended VM is stopped. Neither counts as current Computer evidence any
  more; ``ingest.computer_listing`` turns them into review states.
* Finding type ``archived_but_reporting`` (policy ``conditions-registry-4``):
  every Hudu asset is archived, but an agent or a running VM still reports.
* ``device_missing_from_source`` reworded: one finding per Computer whose
  reason names what is left (documentation only, a stopped VM only, archived
  but still listed, nothing listed).
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations, models

POLICY_VERSION = "conditions-registry-4"
NEW_TYPE = "archived_but_reporting"

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'record_lifecycle.evidence',
    'ADR-0032: documentation and stopped VMs are listed, not evidence that a machine exists.',
    '{"migration": "0310_listing_evidence_and_retirement"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0310', NULL, true);

INSERT INTO operations.source_record_lifecycle_mappings
    (source_id, external_namespace, entity_type, canonical_field, match_value, lifecycle,
     counts_as_current_computer_evidence, priority, enabled)
VALUES
    ((SELECT id FROM operations.sources WHERE name = 'Hudu'), '', 'cmdb.asset', 'archived',
     'false'::jsonb, 'documentation', FALSE, 100, TRUE),
    (NULL, '', 'vm.guest', 'power_state', '"poweredoff"'::jsonb, 'stopped', FALSE, 100, TRUE),
    (NULL, '', 'vm.guest', 'power_state', '"suspended"'::jsonb, 'stopped', FALSE, 100, TRUE)
ON CONFLICT DO NOTHING;

UPDATE operations.finding_types
   SET description = 'Nothing reports for this Computer any more. The reason says what still '
           || 'lists it: documentation only (a current Hudu asset), a stopped VM only, '
           || 'archived documentation beside records that are still listed, or nothing. '
           || 'Archive or remove what is left, or investigate the missing agents.'
 WHERE name = 'device_missing_from_source';
"""


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    if NEW_TYPE not in {item.get("name") for item in policy["definitions"]}:
        policy["definitions"].append(
            {"name": NEW_TYPE, "rules": ["parent_open"], "lifecycle": "active"}
        )
    return policy


def digest(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def register_finding_type(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        # Every NOT NULL column without a default (production 2026-10-16).
        cursor.execute(
            """
            INSERT INTO operations.finding_types (
                name, default_severity, finding_class, source_module, subject_scope,
                creates_device_exposure, auto_resolvable, suppressed_by_approval,
                concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
                description, display_name, issue_category, issue_group, sort_order,
                alertable, covered_by, cover_note
            ) VALUES (%s, 'medium', 'entity', 'evaluator', 'device', TRUE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Inventory', 'Computer lifecycle', 80,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "Every Hudu asset of this Computer is archived, but an agent or a running VM "
                "still reports. Restore the asset in Hudu, or decommission the machine.",
                "Archived but still reporting",
            ),
        )
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE active "
            "ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            return
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0309_identity_findings_and_split"),
    ]

    operations: ClassVar[list] = [
        migrations.AlterField(
            model_name="sourcerecordlifecyclemapping",
            name="lifecycle",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("archived", "Archived"),
                    ("retired", "Retired"),
                    ("decommissioned", "Decommissioned"),
                    ("documentation", "Documentation"),
                    ("stopped", "Stopped"),
                    ("unknown", "Unknown"),
                ],
                max_length=24,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
