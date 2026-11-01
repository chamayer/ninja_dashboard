"""Retry software refreshes that failed on the duplicate-title history bug.

0.138.x wrote source-record software history in one statement whose close and
insert had no ordering, and did not collapse a list naming one title twice, so
those Computers' refreshes failed on ``source_record_software_history_open``
until their attempt limit. Return one row per Computer to pending (only where
none is pending already, as the queue allows one) so the fixed worker refreshes
them.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE ninja_core.software_activity_queue q
   SET status = 'pending', attempts = 0, error = NULL, queued_at = now(),
       started_at = NULL, completed_at = NULL, worker_id = NULL, job_run_id = NULL
  FROM (
      SELECT DISTINCT ON (f.df) f.id
        FROM ninja_core.software_activity_queue f
       WHERE f.status = 'failed'
         AND f.error LIKE '%source_record_software_history_open%'
         AND NOT EXISTS (
             SELECT 1 FROM ninja_core.software_activity_queue p
              WHERE p.df = f.df AND p.status IN ('pending', 'processing'))
       ORDER BY f.df, f.queued_at DESC, f.id DESC
  ) retry
 WHERE q.id = retry.id;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0391_source_record_dispositions"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
