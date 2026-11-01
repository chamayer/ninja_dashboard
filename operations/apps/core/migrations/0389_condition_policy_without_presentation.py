"""Remove presentation keys that 0387 put into a schema 2 condition policy.

``conditions-registry-12`` gave ``entity_link_divergence`` and
``source_record_policy_incomplete`` a label, category and type. Schema 2
definitions must not carry presentation (it comes from ``finding_types``), so
``parse_profile`` rejected the active policy and every condition assessment
failed. This publishes ``conditions-registry-13`` without those keys.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-13"
PRESENTATION_KEYS = ("label", "category", "type")


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    if str(policy.get("schema_version")) == "2":
        for definition in policy.get("definitions", []):
            for key in PRESENTATION_KEYS:
                definition.pop(key, None)
    return policy


def register_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions "
            "WHERE active ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            raise RuntimeError("an active condition policy is required")
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0388_requeue_failed_source_record_assessments"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_policy, migrations.RunPython.noop),
        migrations.RunSQL(
            """
            UPDATE operations.source_record_assessment_queue
               SET status = 'pending', attempts = 0, last_error = '', queued_at = now()
             WHERE status = 'failed' OR attempts > 0;
            """,
            migrations.RunSQL.noop,
        ),
    ]
