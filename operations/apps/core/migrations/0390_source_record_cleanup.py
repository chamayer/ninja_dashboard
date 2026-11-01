"""Stale source-record cleanup, purpose default and attached contradictions.

User decisions 2026-11-01: one stale threshold for every source (the tenant's
retire-review setting), purpose allowed unless a rule restricts it, and an
attached record whose corroborated serial/VM UUID points to another Computer
raises the identity review. This registers the cleanup finding type and the
``ingest_run_slowdown`` admin-health type (both not alertable, Medium), adds their definitions to the condition policy (schema 2:
name, lifecycle and rules only) and requeues every record for the new rules.
"""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations

POLICY_VERSION = "conditions-registry-14"
TYPE_NAME = "source_record_cleanup"

TYPE_SQL = r"""
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval,
    concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
    description, display_name, issue_category, issue_group, sort_order,
    alertable, covered_by, cover_note, allowed_subject_kinds
) VALUES (
    'source_record_cleanup', 'medium', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'An agent record has not contacted its source for longer than the retire-review '
    'threshold while it is unattached or its Computer still reports through other '
    'sources. Remove the leftover record at the source or reinstall the agent.',
    'Source record is stale', 'Inventory', 'Source data', 84,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
) ON CONFLICT (name) DO NOTHING;
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval,
    concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
    description, display_name, issue_category, issue_group, sort_order,
    alertable, covered_by, cover_note, allowed_subject_kinds
) VALUES (
    'ingest_run_slowdown', 'medium', 'admin', 'ingest.platform_findings',
    'device', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'A collection Job has run more than twice as long as its usual time, and at least '
    'five minutes longer, over the last six hours.',
    'Data collection is running slowly', 'Data collection', 'Jobs control plane', 645,
    FALSE, '[]'::jsonb, '', ARRAY[]::text[]
) ON CONFLICT (name) DO NOTHING;
"""


def register_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(TYPE_SQL)
        cursor.execute(
            "SELECT 1 FROM operations.condition_policy_versions WHERE version = %s",
            (POLICY_VERSION,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "SELECT policy FROM operations.condition_policy_versions "
                "WHERE active ORDER BY version DESC LIMIT 1"
            )
            active = cursor.fetchone()
            if active is None:
                raise RuntimeError("an active condition policy is required")
            policy = active[0] if not isinstance(active[0], str) else json.loads(active[0])
            policy = json.loads(json.dumps(policy))
            policy["version"] = POLICY_VERSION
            names = {d.get("name") for d in policy["definitions"]}
            if TYPE_NAME not in names:
                policy["definitions"].append(
                    {"name": TYPE_NAME, "rules": ["parent_open"], "lifecycle": "active"}
                )
            if "ingest_run_slowdown" not in names:
                policy["definitions"].append(
                    {"name": "ingest_run_slowdown", "rules": [], "lifecycle": "active"}
                )
            digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            cursor.execute(
                "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
                (POLICY_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
            )
        cursor.execute(
            """
            SELECT operations.source_record_enqueue(tenant_id, 'source_record', id)
              FROM operations.source_record_subjects WHERE subject_kind = 'record'
            """
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0389_condition_policy_without_presentation"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(register_policy, migrations.RunPython.noop),
    ]
