"""Persist factual stage telemetry for durable Jobs work."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
ALTER TABLE operations.operator_job_runs
    ADD COLUMN stage TEXT NOT NULL DEFAULT 'Queued',
    ADD COLUMN stage_detail TEXT NOT NULL DEFAULT '',
    ADD COLUMN stage_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE operations.operator_job_runs
   SET stage = CASE status
       WHEN 'queued' THEN 'Queued'
       WHEN 'running' THEN 'Running'
       WHEN 'completed' THEN 'Completed'
       WHEN 'failed' THEN 'Failed'
       WHEN 'stalled' THEN 'Needs attention'
       WHEN 'cancelled' THEN 'Cancelled'
       ELSE status
   END,
       stage_updated_at = COALESCE(completed_at, started_at, requested_at);
"""

REVERSE_SQL = """
ALTER TABLE operations.operator_job_runs
    DROP COLUMN IF EXISTS stage_updated_at,
    DROP COLUMN IF EXISTS stage_detail,
    DROP COLUMN IF EXISTS stage;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0178_operator_job_queue"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
