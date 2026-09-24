"""Seed a reviewed policy draft that separates the remaining finding workflows."""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations


SOURCE_VERSION = "conditions-taxonomy-5"
NEW_VERSION = "conditions-taxonomy-6"


def seed_policy(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE version=%s",
            (SOURCE_VERSION,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Required policy {SOURCE_VERSION} is not available")
        policy = row[0]
        if isinstance(policy, str):
            policy = json.loads(policy)
        policy = json.loads(json.dumps(policy))
        policy["version"] = NEW_VERSION
        for category in policy["issue_taxonomy"]:
            if category["key"] != "inventory":
                continue
            for index, type_item in enumerate(category["types"]):
                if type_item["key"] == "client_organization_matching":
                    category["types"][index:index + 1] = [
                        {"key": "client_name_differences", "label": "Client name differences", "conditions": ["client_name_conflict"]},
                        {"key": "client_source_mapping", "label": "Unmapped client source groups", "conditions": ["client_link_collision", "client_unattached_group", "unnamed_source_group", "unmatched_source_group"]},
                    ]
                    break
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0186_jobs_software_supersession")]
    operations: ClassVar[list] = [migrations.RunPython(seed_policy, migrations.RunPython.noop)]
