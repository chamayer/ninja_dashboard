"""Label drift is surfaced, not hidden (ADR-0034 section 9).

Registers ``computer_name_differs_in_source``: a current label (LogMeIn host
name, Hudu asset not archived, R-U-ON monitor, VM name, ...) whose name key
differs from a Computer name decided by an OS rule. One issue per Computer and
labeling system; non-alerting; it resolves when the label matches again. The
fix is at the source. The producer is ``ingest.identity.findings``.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-9"
NEW_TYPE = "computer_name_differs_in_source"


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
        cursor.execute(
            """
            SELECT operations.begin_change(
                'finding_type.add', 'ADR-0034: label drift is surfaced.',
                '{"migration": "0330_computer_name_differs_in_source"}'::jsonb,
                'migration', NULL, 'operations.migrations', '0330', NULL, true)
            """
        )
        # Every NOT NULL column without a default (production 2026-10-16).
        cursor.execute(
            """
            INSERT INTO operations.finding_types (
                name, default_severity, finding_class, source_module, subject_scope,
                creates_device_exposure, auto_resolvable, suppressed_by_approval,
                concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
                description, display_name, issue_category, issue_group, sort_order,
                alertable, covered_by, cover_note
            ) VALUES (%s, 'low', 'entity', 'identity.findings', 'device', FALSE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Inventory', 'Source data', 60,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "A source labels this Computer with a name that differs from the name the "
                "machine reports. Correct the label in that source; the issue resolves when "
                "it matches.",
                "Source label differs from the Computer name",
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
        ("operations", "0329_retire_hostname_authority"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
