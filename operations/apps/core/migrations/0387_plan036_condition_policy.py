"""Register every PLAN-036 condition definition in one policy version.

Activating a condition policy recomputes finding state for every finding; in
0.137.2 one activation kept Operations unavailable for about five minutes. The
PLAN-036 migrations therefore register their finding types only, and this
migration adds all their definitions in one version (one activation):

* native source-record risks and references (``parent_open``, active);
* ``entity_link_divergence`` (admin health, no parent rule);
* ``source_record_policy_incomplete`` moved to admin health by 0385 (no parent rule).
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-12"
PARENT_OPEN_TYPES = (
    "source_record_vulnerable_software",
    "source_record_rejected_software",
    "source_record_unauthorized_tool",
    "source_record_suspicious_software",
    "source_record_malicious_software_hint",
    "source_record_reference_review",
)
HEALTH_DEFINITIONS = {
    "entity_link_divergence": {
        "label": "Entity-link projection divergence",
        "category": "System Health",
        "type": "Association integrity",
    },
    "source_record_policy_incomplete": {
        "label": "Source record role policy is missing",
        "category": "System Health",
        "type": "Source configuration",
    },
}


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    definitions = policy.setdefault("definitions", [])
    by_name = {item.get("name"): item for item in definitions}
    for name in PARENT_OPEN_TYPES:
        if name not in by_name:
            definitions.append({"name": name, "rules": ["parent_open"], "lifecycle": "active"})
    for name, attributes in HEALTH_DEFINITIONS.items():
        definition = by_name.get(name)
        if definition is None:
            definition = {"name": name}
            definitions.append(definition)
        definition.update(attributes)
        definition["lifecycle"] = "active"
        definition["rules"] = []
    return policy


def register_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        exists = cursor.fetchone() is not None
    if not exists:
        _create_policy(schema_editor)
    # Version boundary: the new ingest and Jobs worker wait for this release's
    # schema (policy columns, condition definitions) before admitting work.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("UPDATE operations.finding_contract SET version = 6, published_at = now()")


def _create_policy(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions "
            "WHERE active ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            raise RuntimeError("PLAN-036 conditions require an active condition policy")
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0386_source_record_reference_review"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_policy, migrations.RunPython.noop),
    ]
