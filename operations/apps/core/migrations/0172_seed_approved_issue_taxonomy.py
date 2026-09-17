"""Seed the approved operator taxonomy as a new immutable policy version.

The version is deliberately created inactive. An Operations administrator must
review the exact policy document and activate it through the governed policy
workflow; the Issues page has a compatibility reader for the prior version
while that review is pending.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-taxonomy-1"
POLICY_PAYLOAD = "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"


def seed_taxonomy(apps, schema_editor):
    source = json.loads(zlib.decompress(base64.b64decode(POLICY_PAYLOAD)))
    digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(source)),
        )


def remove_taxonomy(apps, schema_editor):
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
            "DELETE FROM operations.condition_policy_versions WHERE version=%s AND NOT active",
            (NEW_VERSION,),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0171_patch_run_snapshot_association"),
    ]
    operations: ClassVar[list] = [migrations.RunPython(seed_taxonomy, remove_taxonomy)]
