"""Register the rebuilt software inventory's finding types and activate a policy.

Two finding types (user decision 2026-10-13, activated with this migration):

* ``software_inventory_held`` (admin): a computer whose software list from
  Ninja suddenly shrank sharply has its removals held; additions and changes
  still apply. Emitted by the platform-health evaluator from
  ``operations.software_inventory_devices``; it resolves once an administrator
  allows the removals and the next list applies them.
* ``rejected_software_installed`` (entity, per title): software whose effective
  decision is reject is still installed. Emitted by the software reconcile; an
  approval never silences it.

The condition policy must define every registered finding type, so the active
policy is copied with both definitions and taxonomy entries added, created
through ``create_condition_policy_version`` (which validates it and records
its per-type rows) and activated in the same migration. Activation marks
assessments of earlier policy versions as not current until each evaluator
runs again.

The retired software scheduled and demand queues are disabled in the queue
registry so queue health no longer measures them.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-software-inventory-1"

FINDING_TYPES = (
    # name, severity, class, category, source_module, scope, exposure,
    # auto_resolvable, suppressed_by_approval, concern_signal, description
    (
        "software_inventory_held", "medium", "admin", "platform_health",
        "ingest.platform_findings", "device", False, True, False, False,
        "A computer's software list from Ninja shrank sharply, so its removals wait "
        "for an administrator. Additions and changes still apply.",
    ),
    (
        "rejected_software_installed", "high", "entity", "software",
        "platform.software_findings", "software_product", True, True, False, True,
        "Software an operator rejected is still installed.",
    ),
)

DEFINITIONS = (
    {
        "name": "software_inventory_held",
        "label": "Software list held for review",
        "category": "System Health",
        "type": "Collection problem",
        "lifecycle": "active",
        "rules": [],
    },
    {
        "name": "rejected_software_installed",
        "label": "Rejected software is installed",
        "category": "Software & Security",
        "type": "Software approval needed",
        "lifecycle": "active",
        "rules": ["identity"],
    },
)

# (issue category key, issue type key, condition name)
TAXONOMY = (
    ("data_collection", "collection_failures", "software_inventory_held"),
    ("software_security", "software_approval", "rejected_software_installed"),
)

RETIRED_QUEUES = ("software.scheduled", "software.demand")


def build_policy(active: dict) -> dict:
    """The active policy plus this migration's definitions and taxonomy."""
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    definitions = policy.setdefault("definitions", [])
    existing = {item.get("name") for item in definitions}
    definitions.extend(item for item in DEFINITIONS if item["name"] not in existing)
    for category_key, type_key, condition in TAXONOMY:
        category = next(
            (item for item in policy.get("issue_taxonomy", []) if item.get("key") == category_key),
            None,
        )
        if category is None:
            raise RuntimeError(f"Issue category {category_key} is missing from the policy")
        issue_type = next(
            (item for item in category.get("types", []) if item.get("key") == type_key), None
        )
        if issue_type is None:
            raise RuntimeError(f"Issue type {category_key}/{type_key} is missing from the policy")
        conditions = issue_type.setdefault("conditions", [])
        if condition not in conditions:
            conditions.append(condition)
    return policy


def digest(policy: dict) -> str:
    # The same digest ingest verifies when it loads the active policy.
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def register(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for (name, severity, finding_class, category, source_module, scope, exposure,
             auto_resolvable, suppressed, concern, description) in FINDING_TYPES:
            cursor.execute(
                "SELECT id FROM operations.finding_categories WHERE name = %s", (category,)
            )
            category_row = cursor.fetchone()
            if category_row is None:
                raise RuntimeError(f"Finding category {category} is missing")
            cursor.execute(
                """
                INSERT INTO operations.finding_types (
                    name, default_severity, finding_class, category_id, source_module,
                    subject_scope, creates_device_exposure, auto_resolvable,
                    suppressed_by_approval, concern_signal, default_decision_scope,
                    drilldown_evidence_key, runbook_path, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'global', '', '', %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (name, severity, finding_class, category_row[0], source_module, scope,
                 exposure, auto_resolvable, suppressed, concern, description),
            )
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
            if active is None:
                raise RuntimeError("Registering software inventory types needs an active policy")
            current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
            policy = build_policy(current)
            cursor.execute(
                "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
                (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
            )
        cursor.execute(
            "UPDATE operations.queue_registry SET enabled = FALSE WHERE queue_key = ANY(%s)",
            (list(RETIRED_QUEUES),),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0285_software_inventory_devices"),
    ]
    operations: ClassVar[list] = [migrations.RunPython(register, migrations.RunPython.noop)]
