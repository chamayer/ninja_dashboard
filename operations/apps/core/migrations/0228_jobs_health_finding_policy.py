"""Register governed Admin Health conditions for the Jobs control plane."""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations


_CONDITIONS = (
    ("jobs_schedule_failure", "Scheduled Job failed"),
    ("jobs_required_disabled", "Required Job is disabled"),
    ("jobs_queue_backlog", "Jobs queue delayed"),
    ("jobs_repeated_failure", "Job fails repeatedly"),
    ("jobs_timeout", "Job timed out"),
    ("jobs_registry_mismatch", "Jobs registry mismatch"),
    ("jobs_unmet_dependency", "Job dependency is unmet"),
)
_POLICY_VERSION = "conditions-jobs-health-1"


def register_jobs_health_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM operations.finding_categories WHERE name = 'platform_health'"
        )
        category = cursor.fetchone()
        if category is None:
            raise RuntimeError("Jobs health requires the platform_health finding category")
        for name, description in _CONDITIONS:
            cursor.execute(
                """
                INSERT INTO operations.finding_types (
                    name, default_severity, finding_class, category_id, source_module,
                    subject_scope, creates_device_exposure, auto_resolvable,
                    suppressed_by_approval, drilldown_evidence_key, runbook_path, description
                ) VALUES (%s, 'high', 'admin', %s, 'ingest.platform_findings',
                          'device', FALSE, TRUE, FALSE, '', '', %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, category[0], description),
            )
        cursor.execute(
            """SELECT version, policy FROM operations.condition_policy_versions
                 WHERE active ORDER BY version DESC LIMIT 1"""
        )
        active = cursor.fetchone()
        if active is None:
            raise RuntimeError("Jobs health requires an active condition policy")
        policy = active[1]
        if isinstance(policy, str):
            policy = json.loads(policy)
        policy = json.loads(json.dumps(policy))
        policy["version"] = _POLICY_VERSION
        definitions = policy.setdefault("definitions", [])
        existing = {item.get("name") for item in definitions}
        for name, label in _CONDITIONS:
            if name not in existing:
                definitions.append(
                    {
                        "name": name,
                        "label": label,
                        "category": "System Health",
                        "type": "Jobs control plane",
                        "lifecycle": "active",
                        "rules": [],
                    }
                )
        for category_item in policy.get("issue_taxonomy", []):
            if category_item.get("key") != "data_collection":
                continue
            types = category_item.setdefault("types", [])
            jobs_type = next((item for item in types if item.get("key") == "jobs_health"), None)
            if jobs_type is None:
                types.append(
                    {
                        "key": "jobs_health",
                        "label": "Jobs control plane",
                        "conditions": [name for name, _label in _CONDITIONS],
                    }
                )
            else:
                jobs_type["conditions"] = [name for name, _label in _CONDITIONS]
            break
        else:
            raise RuntimeError("Jobs health requires the data_collection issue category")
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        cursor.execute(
            "UPDATE operations.condition_policy_versions SET active = FALSE WHERE active"
        )
        cursor.execute(
            """INSERT INTO operations.condition_policy_versions (version, digest, policy, active)
                 VALUES (%s, %s, %s::jsonb, TRUE)""",
            (_POLICY_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0227_jobs_schedule_terminal_outcomes"),
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(register_jobs_health_policy, migrations.RunPython.noop),
    ]
