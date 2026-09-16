"""Promote the six policy-defined issue categories to the active policy."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import ClassVar

from django.db import migrations


NEW_VERSION = "conditions-policy-2"


def promote_categories(apps, schema_editor):
    source = json.loads(
        resources.files("shared.conditions").joinpath("profile.json").read_text(encoding="utf-8")
    )
    source["version"] = NEW_VERSION
    source["issue_categories"] = [
        {"key": "computers", "label": "Computers", "categories": ["Computers"]},
        {"key": "documentation", "label": "Documentation", "categories": ["Documentation"]},
        {"key": "records_matching", "label": "Records & Matching", "categories": ["Records & Matching"]},
        {"key": "security_software", "label": "Software & Security", "categories": ["Software & Security"]},
        {"key": "system_health", "label": "System Health", "categories": ["System Health"]},
        {"key": "updates_support", "label": "Updates & Support", "categories": ["Updates & Support"]},
    ]
    digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(source)),
        )
        cursor.execute(
            "SELECT operations.activate_condition_policy_version(%s)",
            (NEW_VERSION,),
        )


def restore_previous_policy(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.activate_condition_policy_version(%s)",
            ("conditions-shadow-1",),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0163_condition_assessment_policy_digest"),
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(promote_categories, restore_previous_policy),
    ]
