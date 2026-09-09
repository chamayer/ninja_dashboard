"""Add a policy-owned source-record lifecycle contract for Computers."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models
import django.db.models.deletion


VIEW_SQL = """
CREATE VIEW operations.v_device_source_record_lifecycle_current
WITH (security_barrier = true) AS
SELECT observation.observation_id,
       observation.tenant_id,
       observation.device_id,
       observation.source_instance_id,
       source.id AS source_id,
       source.name AS source_name,
       observation.platform,
       observation.entity_type,
       observation.external_namespace,
       observation.external_id,
       observation.active AS source_record_current,
       observation.last_seen_at,
       COALESCE(mapping.lifecycle, 'unknown') AS record_lifecycle,
       observation.active
         AND COALESCE(mapping.counts_as_current_computer_evidence, TRUE)
           AS counts_as_current_computer_evidence
  FROM operations.entity_observation_current observation
  JOIN operations.source_instances source_instance
    ON source_instance.tenant_id = observation.tenant_id
   AND source_instance.id = observation.source_instance_id
  JOIN operations.sources source ON source.id = source_instance.source_id
  LEFT JOIN LATERAL (
      SELECT mapping.lifecycle, mapping.counts_as_current_computer_evidence
        FROM operations.source_record_lifecycle_mappings mapping
       WHERE mapping.enabled
         AND (mapping.source_id IS NULL OR mapping.source_id = source.id)
         AND (mapping.external_namespace = ''
              OR mapping.external_namespace = observation.external_namespace)
         AND (mapping.entity_type = '' OR mapping.entity_type = observation.entity_type)
         AND observation.canonical_data -> mapping.canonical_field = mapping.match_value
       ORDER BY mapping.priority, mapping.id
       LIMIT 1
  ) mapping ON TRUE
 WHERE observation.tenant_id = operations.current_tenant_id();

ALTER VIEW operations.v_device_source_record_lifecycle_current
    OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_device_source_record_lifecycle_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_device_source_record_lifecycle_current
TO operations_app, operations_readonly, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_device_source_record_lifecycle_current
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


ACCESS_SQL = """
REVOKE ALL ON operations.source_record_lifecycle_mappings
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.source_record_lifecycle_mappings
TO operations_app;
GRANT SELECT ON operations.source_record_lifecycle_mappings
TO operations_view_owner;
GRANT USAGE, SELECT ON SEQUENCE operations.source_record_lifecycle_mappings_id_seq
TO operations_app;
"""


SEED_SQL = """
INSERT INTO operations.source_record_lifecycle_mappings (
    source_id, external_namespace, entity_type, canonical_field, match_value,
    lifecycle, counts_as_current_computer_evidence, priority, enabled
)
SELECT source.id, '', 'cmdb.asset', 'archived', 'true'::jsonb,
       'archived', FALSE, 100, TRUE
  FROM operations.sources source
 WHERE source.name = 'Hudu'
ON CONFLICT (source_id, external_namespace, entity_type, canonical_field, match_value)
DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0157_no_current_sources_finding_label")]

    operations: ClassVar = [
        migrations.CreateModel(
            name="SourceRecordLifecycleMapping",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("external_namespace", models.CharField(blank=True, default="", max_length=120)),
                ("entity_type", models.CharField(blank=True, default="", max_length=80)),
                ("canonical_field", models.CharField(max_length=160)),
                ("match_value", models.JSONField()),
                ("lifecycle", models.CharField(choices=[("active", "Active"), ("archived", "Archived"), ("retired", "Retired"), ("decommissioned", "Decommissioned"), ("unknown", "Unknown")], max_length=24)),
                ("counts_as_current_computer_evidence", models.BooleanField(default=True)),
                ("priority", models.PositiveIntegerField(default=100)),
                ("enabled", models.BooleanField(default=True)),
                ("source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="record_lifecycle_mappings", to="operations.source")),
            ],
            options={"db_table": "source_record_lifecycle_mappings", "ordering": ("source", "external_namespace", "entity_type", "priority", "id")},
        ),
        migrations.AddConstraint(
            model_name="sourcerecordlifecyclemapping",
            constraint=models.UniqueConstraint(fields=("source", "external_namespace", "entity_type", "canonical_field", "match_value"), name="uq_source_record_lifecycle_mapping", nulls_distinct=False),
        ),
        migrations.RunSQL(ACCESS_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(SEED_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(VIEW_SQL, "DROP VIEW IF EXISTS operations.v_device_source_record_lifecycle_current;"),
    ]
