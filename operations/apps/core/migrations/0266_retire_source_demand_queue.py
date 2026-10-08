"""Retire the superseded source-demand queue without deleting its audit trail."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
UPDATE operations.job_schedules
   SET enabled = FALSE,
       capability_reason = 'Replaced by binding-scoped source refreshes.',
       next_due_at = NULL
 WHERE tenant_id = 1
   AND definition_key IN ('source-demand', 'source-demand-recovery');

UPDATE operations.source_run_queue
   SET status = 'failed', completed_at = now(),
       error = 'Superseded by binding-scoped source refreshes.'
 WHERE tenant_id = 1 AND status IN ('pending', 'processing');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0265_reference_sources")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
