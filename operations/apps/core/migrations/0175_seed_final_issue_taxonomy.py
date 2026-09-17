"""Seed the final revised Issues taxonomy as a new immutable policy version."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-taxonomy-4"
POLICY_DIGEST = "6bc2000178f5b098db29b05d7d770a8d173e1a8e085a5e690ab6603a6973f9d2"
POLICY_PAYLOAD = "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"


def seed_final_policy(apps, schema_editor):
    policy = json.loads(zlib.decompress(base64.b64decode(POLICY_PAYLOAD)))
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    if digest != POLICY_DIGEST or policy["version"] != NEW_VERSION:
        raise RuntimeError("Embedded taxonomy payload does not match its declared digest")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(policy)),
        )


def remove_final_policy(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM operations.condition_policy_reviews WHERE version=%s",
            (NEW_VERSION,),
        )
        cursor.execute(
            "DELETE FROM operations.condition_policies WHERE policy_version=%s",
            (NEW_VERSION,),
        )
        cursor.execute(
            "DELETE FROM operations.condition_policy_versions "
            "WHERE version=%s AND NOT active",
            (NEW_VERSION,),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0174_seed_revised_issue_taxonomy"),
    ]
    operations: ClassVar[list] = [
        migrations.RunPython(seed_final_policy, remove_final_policy)
    ]
