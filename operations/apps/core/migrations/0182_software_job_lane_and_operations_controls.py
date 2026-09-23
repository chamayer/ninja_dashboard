"""Make Software classifier work independently schedulable and controllable."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
GRANT SELECT, INSERT, UPDATE ON operations.operator_job_runs TO operations_app;

UPDATE operations.operator_job_runs
   SET lane = 'software'
 WHERE job_key IN ('software-classify', 'software-classify-only', 'software-classify-full');

-- A queued full rebuild subsumes a queued incremental run. Auto-intel is the
-- broadest classifier mode and likewise subsumes either queued lower mode.
UPDATE operations.operator_job_runs narrow
   SET status = 'cancelled', stage = 'Superseded',
       stage_detail = 'Superseded by a broader Software classifier run.',
       stage_updated_at = now(), completed_at = now(),
       error = 'Superseded before work started.'
 WHERE narrow.status = 'queued'
   AND narrow.job_key IN ('software-classify-only', 'software-classify-full')
   AND EXISTS (
       SELECT 1 FROM operations.operator_job_runs broad
        WHERE broad.tenant_id = narrow.tenant_id
          AND broad.status IN ('queued', 'running')
          AND (
              (narrow.job_key = 'software-classify-only'
               AND broad.job_key IN ('software-classify-full', 'software-classify'))
              OR (narrow.job_key = 'software-classify-full'
                  AND broad.job_key = 'software-classify')
          )
   );
"""

REVERSE_SQL = """
REVOKE UPDATE ON operations.operator_job_runs FROM operations_app;
UPDATE operations.operator_job_runs
   SET lane = 'evaluation'
 WHERE lane = 'software'
   AND job_key IN ('software-classify', 'software-classify-only', 'software-classify-full');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0181_software_classifier_incremental_marker"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
