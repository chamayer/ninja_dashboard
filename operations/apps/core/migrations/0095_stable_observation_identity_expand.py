"""Add and backfill ADR-0009 shadow identity columns.

ADR-0007 remains the deployed read/write authority after this migration. The
new columns are nullable or safely empty for forward compatibility; later
dual-write and cutover migrations may make them authoritative only after
shadow comparison and rollback rehearsal.
"""

from __future__ import annotations

from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models

BACKFILL_SQL = """
UPDATE operations.entity_observation_current eo
   SET source_instance_id = sb.source_instance_id,
       last_seen_binding_id = eo.source_binding_id,
       external_namespace = CASE
           WHEN s.name = 'Ninja' AND eo.entity_type = 'org' THEN 'organization'
           WHEN s.name = 'Ninja' THEN 'device'
           WHEN s.name = 'SentinelOne' AND eo.entity_type = 'org' THEN 'site'
           WHEN s.name = 'SentinelOne' THEN 'agent'
           WHEN s.name = 'ScreenConnect' AND eo.entity_type = 'org' THEN 'source-instance'
           WHEN s.name = 'ScreenConnect' THEN 'access-session'
           WHEN s.name = 'LogMeIn' AND eo.entity_type = 'org' THEN 'group'
           WHEN s.name = 'LogMeIn' THEN 'host'
           WHEN s.name = 'Hudu' AND eo.entity_type = 'org' THEN 'company'
           WHEN s.name = 'Hudu' THEN 'asset'
           ELSE ''
       END,
       parent_external_namespace = '',
       parent_external_id = '',
       external_id = CASE
           WHEN s.name = 'ScreenConnect' AND eo.entity_type = 'org' THEN 'self'
           ELSE eo.entity_key
       END
  FROM operations.source_bindings sb
  JOIN operations.source_instances si ON si.id = sb.source_instance_id
  JOIN operations.sources s ON s.id = si.source_id
 WHERE sb.id = eo.source_binding_id;

UPDATE operations.entity_observation_history eh
   SET source_instance_id = sb.source_instance_id,
       last_seen_binding_id = eh.source_binding_id,
       external_namespace = CASE
           WHEN s.name = 'Ninja' AND eh.entity_type = 'org' THEN 'organization'
           WHEN s.name = 'Ninja' THEN 'device'
           WHEN s.name = 'SentinelOne' AND eh.entity_type = 'org' THEN 'site'
           WHEN s.name = 'SentinelOne' THEN 'agent'
           WHEN s.name = 'ScreenConnect' AND eh.entity_type = 'org' THEN 'source-instance'
           WHEN s.name = 'ScreenConnect' THEN 'access-session'
           WHEN s.name = 'LogMeIn' AND eh.entity_type = 'org' THEN 'group'
           WHEN s.name = 'LogMeIn' THEN 'host'
           WHEN s.name = 'Hudu' AND eh.entity_type = 'org' THEN 'company'
           WHEN s.name = 'Hudu' THEN 'asset'
           ELSE ''
       END,
       parent_external_namespace = '',
       parent_external_id = '',
       external_id = CASE
           WHEN s.name = 'ScreenConnect' AND eh.entity_type = 'org' THEN 'self'
           ELSE eh.entity_key
       END
  FROM operations.source_bindings sb
  JOIN operations.source_instances si ON si.id = sb.source_instance_id
  JOIN operations.sources s ON s.id = si.source_id
 WHERE sb.id = eh.source_binding_id;

UPDATE operations.observation_snapshot_runs r
   SET source_instance_id = sb.source_instance_id,
       run_started_at = r.snapshot_at,
       is_complete_snapshot = CASE
           WHEN r.status = 'complete' THEN TRUE
           WHEN r.status = 'failed' THEN FALSE
           ELSE NULL
       END
  FROM operations.source_bindings sb
 WHERE sb.id = r.source_binding_id;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0094_activate_lifecycle_evidence_policy"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="source_instance",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stable_current_observations",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="last_seen_binding",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="stable_current_transport_observations",
                to="operations.sourcebinding",
            ),
        ),
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="external_namespace",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="parent_external_namespace",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="parent_external_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="external_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="source_instance",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stable_history_observations",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="last_seen_binding",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="stable_history_transport_observations",
                to="operations.sourcebinding",
            ),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="external_namespace",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="parent_external_namespace",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="parent_external_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="external_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="observationsnapshotrun",
            name="source_instance",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="observation_snapshot_runs",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AddField(
            model_name="observationsnapshotrun",
            name="run_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="observationsnapshotrun",
            name="is_complete_snapshot",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunSQL(BACKFILL_SQL, migrations.RunSQL.noop),
    ]
