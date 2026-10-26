"""Expose entity and admin findings through one tenant-scoped read contract.

The view is a UNION (and therefore not directly updatable). Invoker security
keeps each source table's tenant RLS in force for the requesting role.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


FORWARD_SQL = r"""
CREATE VIEW operations.v_issue_findings
WITH (security_barrier = true, security_invoker = true) AS
SELECT 'entity'::text AS row_kind,
       finding.id,
       finding.tenant_id,
       finding.finding_type_id,
       finding_type.name AS finding_type_name,
       finding.condition_key,
       finding.severity,
       finding.status,
       finding.subject_type,
       finding.subject_id,
       finding.client_id,
       finding.finding_details AS details,
       finding.first_seen_at AS first_detected_at,
       finding.last_seen_at AS last_detected_at,
       finding.resolved_at
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
UNION ALL
SELECT 'admin'::text AS row_kind,
       finding.id,
       finding.tenant_id,
       finding.finding_type_id,
       finding_type.name AS finding_type_name,
       finding.condition_key,
       finding.severity,
       finding.status,
       NULL::text AS subject_type,
       NULL::uuid AS subject_id,
       NULL::uuid AS client_id,
       finding.details,
       finding.first_detected_at,
       finding.last_detected_at,
       finding.resolved_at
  FROM operations.admin_findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id;

REVOKE ALL ON operations.v_issue_findings FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_issue_findings
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON operations.v_issue_findings
    TO operations_app, operations_readonly, metabase_ro;
"""

REVERSE_SQL = "DROP VIEW IF EXISTS operations.v_issue_findings;"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0351_retired_job_configuration"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.CreateModel(
            name="IssueFindingReadModel",
            fields=[
                ("row_kind", models.CharField(max_length=16)),
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField()),
                ("finding_type_id", models.PositiveSmallIntegerField()),
                ("finding_type_name", models.CharField(max_length=120)),
                ("condition_key", models.CharField(max_length=255)),
                ("severity", models.CharField(max_length=16)),
                ("status", models.CharField(max_length=24)),
                ("subject_type", models.CharField(max_length=32, null=True)),
                ("subject_id", models.UUIDField(null=True)),
                ("client_id", models.UUIDField(null=True)),
                ("details", models.JSONField()),
                ("first_detected_at", models.DateTimeField()),
                ("last_detected_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(null=True)),
            ],
            options={
                "db_table": "v_issue_findings",
                "managed": False,
            },
        ),
    ]
