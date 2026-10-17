"""Retire ``device_source_record_withdrawn`` (ADR-0032 "Withdrawn records").

A withdrawn record is history, not a finding: it is shown on the Computer's
History tab, and its consequences are reported by the findings that own them
(``missing_required_platform``, ``device_missing_from_source``,
``archived_but_reporting``, retirement). Verified in production before this
migration (``verify_withdrawn.sql`` in the plan): every open withdrawal of a
required source is covered by one of those, by a re-registration of the
same source, or the Computer is retired; the remainder are sources that are
not required for that Computer, which ADR-0032 makes a History event only.

The open findings are closed with that reason; the policy marks the type
historical (``conditions-registry-5``); the evaluator no longer produces it.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-5"
RETIRED_TYPE = "device_source_record_withdrawn"

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'finding_type.retire',
    'ADR-0032: a withdrawn source record is history; its consequences have their own findings.',
    '{"migration": "0316_retire_source_record_withdrawn", "finding_type": "device_source_record_withdrawn"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0316', NULL, true);

UPDATE operations.findings f
   SET status = 'resolved',
       closed_at = coalesce(f.closed_at, now()),
       last_seen_at = now(),
       finding_details = f.finding_details || jsonb_build_object('resolution', jsonb_build_object(
           'reason', 'finding_type_retired',
           'detail', 'A withdrawn record is shown on the Computer''s History; missing agents, '
                     || 'cleanup and retirement have their own findings (ADR-0032).',
           'resolved_at', now()))
  FROM operations.finding_types ft
 WHERE ft.id = f.finding_type_id AND ft.name = 'device_source_record_withdrawn'
   AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed');
"""


def build_policy(active: dict) -> dict:
    policy = json.loads(json.dumps(active))
    policy["version"] = POLICY_VERSION
    for item in policy["definitions"]:
        if item.get("name") == RETIRED_TYPE:
            item["lifecycle"] = "historical"
    return policy


def digest(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def activate_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE active "
            "ORDER BY version DESC LIMIT 1"
        )
        active = cursor.fetchone()
        if active is None:
            return
        current = json.loads(active[0]) if isinstance(active[0], str) else active[0]
        policy = build_policy(current)
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (POLICY_VERSION, digest(policy), json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0315_merge_moves_source_links"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
        migrations.RunPython(activate_policy, migrations.RunPython.noop),
    ]
