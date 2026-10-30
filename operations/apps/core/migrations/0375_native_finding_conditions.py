"""Native source-record findings join the shared condition contract (PLAN-004 R4 follow-up).

R4 published native ``source_record`` and ``source_record_case`` findings without
condition assessments or participants, so ``finding_state`` had no current
assessment for them and participant-based readers (rollups, exposure, Computer
aggregation) could not see them. This registers the four native types in a new
active condition policy version (``parent_open``, like the legacy identity types)
and queues every subject and case key that owns an active native finding, so the
assessment worker writes their assessments and participants on its next run.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-11"
NATIVE_TYPES = (
    "source_record_identity_review",
    "source_record_identifier_invalid",
    "source_record_duplicate_review",
    "source_record_policy_incomplete",
)


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    names = {item.get("name") for item in policy["definitions"]}
    for name in NATIVE_TYPES:
        if name not in names:
            policy["definitions"].append(
                {"name": name, "rules": ["parent_open"], "lifecycle": "active"}
            )
    return policy


def digest(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def register_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "SELECT policy FROM operations.condition_policy_versions WHERE active "
                "ORDER BY version DESC LIMIT 1"
            )
            active = cursor.fetchone()
            if active is not None:
                current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
                policy = build_policy(current)
                cursor.execute(
                    "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
                    (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
                )
        cursor.execute(
            """
            SELECT operations.source_record_enqueue(f.tenant_id, 'source_record', f.subject_id)
              FROM operations.findings f
             WHERE f.subject_type = 'source_record'
               AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            """
        )
        cursor.execute(
            """
            SELECT operations.source_record_enqueue(
                       c.tenant_id, 'case_key', c.scope_key,
                       jsonb_build_object('source_instance_id', c.source_instance_id,
                                          'key_family', c.key_family,
                                          'normalized_value', c.key_value))
              FROM operations.source_record_cases c
             WHERE c.state IN ('open', 'duplicate')
            """
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0374_source_association_authority"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_policy, migrations.RunPython.noop),
    ]
