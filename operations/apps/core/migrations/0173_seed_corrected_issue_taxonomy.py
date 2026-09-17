"""Seed the corrected, reviewed five-category Issues policy.

The compressed payload is intentionally embedded here. Migrations must not
read mutable application data at migration time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-taxonomy-2"
POLICY_PAYLOAD = (
    "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"
)


def seed_corrected_policy(apps, schema_editor):
    policy = json.loads(zlib.decompress(base64.b64decode(POLICY_PAYLOAD)))
    # Keep the two final operator-label corrections explicit in the migration
    # payload as well as in the packaged profile.
    labels = {
        "device_role_conflict": "Platforms disagree on computer role",
        "lifecycle_reported_state_conflict": "Platforms disagree on lifecycle status",
    }
    for definition in policy["definitions"]:
        if definition["name"] in labels:
            definition["label"] = labels[definition["name"]]
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(policy)),
        )


def remove_corrected_policy(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DELETE FROM operations.condition_policy_reviews WHERE version=%s", (NEW_VERSION,))
        cursor.execute("DELETE FROM operations.condition_policies WHERE policy_version=%s", (NEW_VERSION,))
        cursor.execute(
            "DELETE FROM operations.condition_policy_versions WHERE version=%s AND NOT active",
            (NEW_VERSION,),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0172_seed_approved_issue_taxonomy"),
    ]
    operations: ClassVar[list] = [migrations.RunPython(seed_corrected_policy, remove_corrected_policy)]
