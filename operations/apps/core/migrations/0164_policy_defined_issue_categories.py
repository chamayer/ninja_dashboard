"""Promote the six policy-defined issue categories to the active policy."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-policy-2"
POLICY_PAYLOAD = "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"


def promote_categories(apps, schema_editor):
    source = json.loads(zlib.decompress(base64.b64decode(POLICY_PAYLOAD)))
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
