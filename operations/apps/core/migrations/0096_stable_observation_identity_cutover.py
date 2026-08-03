"""Cut observation writes and reconciliation over to ADR-0009 identity."""

from __future__ import annotations

from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

PREFLIGHT_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM operations.entity_observation_current
         WHERE source_instance_id IS NULL
            OR external_namespace = ''
            OR external_id = ''
            OR ((parent_external_namespace = '') <> (parent_external_id = ''))
    ) THEN
        RAISE EXCEPTION 'current observations have incomplete stable identity';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.entity_observation_history
         WHERE source_instance_id IS NULL
            OR external_namespace = ''
            OR external_id = ''
            OR ((parent_external_namespace = '') <> (parent_external_id = ''))
    ) THEN
        RAISE EXCEPTION 'observation history has incomplete stable identity';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.observation_snapshot_runs
         WHERE source_instance_id IS NULL OR run_started_at IS NULL
    ) THEN
        RAISE EXCEPTION 'snapshot runs have incomplete stable identity';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.entity_observation_current
         GROUP BY tenant_id, source_instance_id, external_namespace,
                  parent_external_namespace, parent_external_id, external_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'current observations have stable identity collisions';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.entity_observation_history
         WHERE effective_to IS NULL
         GROUP BY tenant_id, source_instance_id, external_namespace,
                  parent_external_namespace, parent_external_id, external_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'open observation history has stable identity collisions';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.observation_snapshot_runs
         GROUP BY tenant_id, source_instance_id, snapshot_scope, snapshot_at
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'snapshot runs have stable boundary collisions';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM operations.entity_observation_current c
          LEFT JOIN operations.entity_observation_history h
            ON h.tenant_id = c.tenant_id
           AND h.source_instance_id = c.source_instance_id
           AND h.external_namespace = c.external_namespace
           AND h.parent_external_namespace = c.parent_external_namespace
           AND h.parent_external_id = c.parent_external_id
           AND h.external_id = c.external_id
           AND h.effective_to IS NULL
         GROUP BY c.observation_id, c.active
        HAVING COUNT(h.id) <> CASE WHEN c.active THEN 1 ELSE 0 END
    ) THEN
        RAISE EXCEPTION 'current presence and open history are inconsistent';
    END IF;
END
$$;
"""


BACKFILL_RUN_COUNTS_SQL = """
UPDATE operations.observation_snapshot_runs
   SET observed_identity_count = written_rows;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0095_stable_observation_identity_expand"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(PREFLIGHT_SQL, migrations.RunSQL.noop),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="closed_by_snapshot_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="closed_observation_history",
                to="operations.observationsnapshotrun",
            ),
        ),
        migrations.AddField(
            model_name="observationsnapshotrun",
            name="observed_identity_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="observationsnapshotrun",
            name="observed_identity_digest",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.RunSQL(BACKFILL_RUN_COUNTS_SQL, migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="entityobservationcurrent",
            name="source_instance",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stable_current_observations",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AlterField(
            model_name="entityobservationhistory",
            name="source_instance",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stable_history_observations",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AlterField(
            model_name="observationsnapshotrun",
            name="source_instance",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="observation_snapshot_runs",
                to="operations.sourceinstance",
            ),
        ),
        migrations.AlterField(
            model_name="observationsnapshotrun",
            name="run_started_at",
            field=models.DateTimeField(),
        ),
        migrations.AddConstraint(
            model_name="entityobservationcurrent",
            constraint=models.UniqueConstraint(
                fields=(
                    "tenant",
                    "source_instance",
                    "external_namespace",
                    "parent_external_namespace",
                    "parent_external_id",
                    "external_id",
                ),
                name="uq_obs_current_stable_identity",
            ),
        ),
        migrations.AddConstraint(
            model_name="entityobservationcurrent",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(external_namespace="")
                    & ~Q(external_id="")
                    & (
                        (Q(parent_external_namespace="") & Q(parent_external_id=""))
                        | (~Q(parent_external_namespace="") & ~Q(parent_external_id=""))
                    )
                ),
                name="ck_obs_current_stable_identity",
            ),
        ),
        migrations.AddConstraint(
            model_name="entityobservationhistory",
            constraint=models.UniqueConstraint(
                condition=Q(effective_to__isnull=True),
                fields=(
                    "tenant",
                    "source_instance",
                    "external_namespace",
                    "parent_external_namespace",
                    "parent_external_id",
                    "external_id",
                ),
                name="uq_obs_hist_open_stable_identity",
            ),
        ),
        migrations.AddConstraint(
            model_name="entityobservationhistory",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(external_namespace="")
                    & ~Q(external_id="")
                    & (
                        (Q(parent_external_namespace="") & Q(parent_external_id=""))
                        | (~Q(parent_external_namespace="") & ~Q(parent_external_id=""))
                    )
                ),
                name="ck_obs_hist_stable_identity",
            ),
        ),
        migrations.AddConstraint(
            model_name="observationsnapshotrun",
            constraint=models.UniqueConstraint(
                fields=("tenant", "source_instance", "snapshot_scope", "snapshot_at"),
                name="uq_obs_snapshot_stable_boundary",
            ),
        ),
    ]
