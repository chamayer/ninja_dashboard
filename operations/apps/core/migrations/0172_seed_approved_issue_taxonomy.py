"""Seed the approved operator taxonomy as a new immutable policy version.

The version is deliberately created inactive. An Operations administrator must
review the exact policy document and activate it through the governed policy
workflow; the Issues page has a compatibility reader for the prior version
while that review is pending.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import ClassVar

from django.db import migrations

NEW_VERSION = "conditions-taxonomy-1"


def seed_taxonomy(apps, schema_editor):
    source = json.loads(
        resources.files("shared.conditions").joinpath("profile.json").read_text(encoding="utf-8")
    )
    source["version"] = NEW_VERSION
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
