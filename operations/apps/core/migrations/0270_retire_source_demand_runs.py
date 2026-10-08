"""Close the retired source-demand Runs without erasing their audit history."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
WITH retired AS (
    UPDATE operations.operator_job_runs
       SET status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE 'failed' END,
           stage = 'Retired',
           stage_detail = 'Superseded by binding-scoped source refreshes.',
           stage_updated_at = now(),
           completed_at = now(),
           heartbeat_at = now(),
           lease_expires_at = NULL,
           deadline_at = NULL,
           wait_category = NULL,
           wait_reason = NULL,
           error = CASE WHEN status = 'queued'
                 THEN 'Cancelled before work started because this source queue was retired.'
                 ELSE 'The source queue was retired while this Run was active; verify effects before retrying.'
             END,
           terminal_reason = CASE WHEN status = 'queued'
                 THEN 'retired-before-start' ELSE 'retired-running-contained' END
     WHERE tenant_id = 1
       AND job_key IN ('source-demand', 'source-demand-recovery')
       AND status IN ('queued', 'running')
 RETURNING id, status
), claims AS (
    UPDATE operations.job_resource_claims claim
       SET state = CASE WHEN retired.status = 'failed' THEN 'contained' ELSE 'released' END,
           released_at = CASE WHEN retired.status = 'failed' THEN NULL ELSE now() END,
           release_reason = CASE WHEN retired.status = 'failed'
                 THEN 'retired source-demand Run contained' ELSE 'retired source-demand Run cancelled' END
      FROM retired
     WHERE claim.tenant_id = 1 AND claim.run_id = retired.id AND claim.state = 'held'
)
INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
SELECT 1, id, 'retired', 'Retired', 'Superseded by binding-scoped source refreshes.'
  FROM retired;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0269_reference_source_history")
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
