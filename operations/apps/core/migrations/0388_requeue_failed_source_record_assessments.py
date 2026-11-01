"""Retry source-record assessments that failed on the 0.138.0 parameter bug.

0.138.0's software-signal query passed eight parameters to a two-placeholder
statement, so every record batch failed and rows reaching the attempt limit were
marked ``failed``. Return them to pending so the fixed worker assesses them.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE operations.source_record_assessment_queue
   SET status = 'pending', attempts = 0, last_error = '', queued_at = now()
 WHERE status = 'failed' OR attempts > 0;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0387_plan036_condition_policy"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
