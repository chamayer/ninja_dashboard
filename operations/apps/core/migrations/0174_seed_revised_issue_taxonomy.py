"""Seed the approved replacement Issues taxonomy as an immutable policy."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-taxonomy-3"
POLICY_DIGEST = "d2df6ec9e6fbffefd7ab588ac2c0a08860dbb051ea051c9828522c0a0a7aa945"
POLICY_PAYLOAD = "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"


def seed_revised_policy(apps, schema_editor):
    policy = json.loads(zlib.decompress(base64.b64decode(POLICY_PAYLOAD)))
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    if digest != POLICY_DIGEST or policy["version"] != NEW_VERSION:
        raise RuntimeError("Embedded taxonomy payload does not match its declared digest")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(policy)),
        )


def remove_revised_policy(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM operations.condition_policy_reviews WHERE version=%s", (NEW_VERSION,)
        )
        cursor.execute(
            "DELETE FROM operations.condition_policies WHERE policy_version=%s", (NEW_VERSION,)
        )
        cursor.execute(
            "DELETE FROM operations.condition_policy_versions WHERE version=%s AND NOT active",
            (NEW_VERSION,),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0173_seed_corrected_issue_taxonomy"),
    ]
    operations: ClassVar[list] = [migrations.RunPython(seed_revised_policy, remove_revised_policy)]
