"""Unknown operating system never silently means "no requirements" (ADR-0032 follow-up).

Measured 2026-10-18: 160 Computers in the coverage check have
``os_group = 'Unknown'`` and every OS-dependent agent requirement was skipped
for them, so a missing agent was reported nowhere. The evaluator now applies
such a requirement when the agent's earlier presence on the Computer (or its
role together with an agent supported on every OS group) establishes it, and
otherwise reports one finding per Computer, ``os_unknown_coverage``, listing
the requirements it could not evaluate. Missing agents are never assumed, so
monitored appliances do not raise false alarms.

Finding type ``os_unknown_coverage`` and policy ``conditions-registry-6``.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-6"
NEW_TYPE = "os_unknown_coverage"


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
            ) VALUES (%s, 'medium', 'entity', 'evaluator', 'device', FALSE, TRUE, FALSE,
                      FALSE, 'global', '', '', %s, %s, 'Agents & reporting', 'Coverage', 40,
                      FALSE, '[]'::jsonb, '')
            ON CONFLICT (name) DO NOTHING
            """,
            (
                NEW_TYPE,
                "The Computer's operating system is unknown, so required agents that depend "
                "on it could not be checked. Missing agents are not assumed. Confirm what the "
                "machine is (its OS, or that it is an appliance) or exempt it.",
                "Operating system unknown: coverage not evaluated",
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
        ("operations", "0319_audit_log_cutover"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_finding_type, migrations.RunPython.noop),
    ]
