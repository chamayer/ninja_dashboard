"""Quiesce legacy version-0 Jobs before removing their in-process worker."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
WITH transitioned AS (
    UPDATE operations.operator_job_runs
       SET status = CASE status WHEN 'queued' THEN 'cancelled' ELSE 'stalled' END,
           stage = CASE status
               WHEN 'queued' THEN 'Cancelled'
               ELSE 'Needs attention'
           END,
           stage_detail = CASE status
               WHEN 'queued' THEN 'Legacy request was quiesced during the durable Jobs cutover.'
               ELSE 'Legacy execution cannot survive the Jobs worker cutover.'
           END,
           stage_updated_at = now(), completed_at = now(), lease_expires_at = NULL,
           error = CASE status
               WHEN 'queued' THEN 'Retry to create a governed Jobs run.'
               ELSE 'Verify external effects, then retry when safe.'
           END,
           terminal_reason = CASE status
               WHEN 'queued' THEN 'legacy_cutover_cancelled'
               ELSE 'legacy_cutover_interrupted'
           END
     WHERE tenant_id = 1 AND contract_version = 0
       AND status IN ('queued', 'running')
 RETURNING tenant_id, id, status, stage, stage_detail
)
INSERT INTO operations.operator_job_events (
    tenant_id, job_id, event_type, stage, detail
)
SELECT tenant_id, id,
       CASE status WHEN 'cancelled' THEN 'cancelled' ELSE 'stalled' END,
       stage, stage_detail
  FROM transitioned;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0219_jobs_software_domain_attempts"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
