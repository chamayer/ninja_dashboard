"""Close the pre-ledger software activity queue alert that nothing reassesses.

The queue alert for ``software.activity`` was raised in the entity namespace
before platform health moved to the admin ledger; the admin evaluator never
reads it. Last detected 2026-09-29; the queue has no failed or pending entries
(checked read-only 2026-11-02). Close it with that reason, keeping its details.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE operations.findings f
   SET status = 'resolved', closed_at = now(),
       finding_details = f.finding_details || jsonb_build_object(
           'closure_reason',
           'Superseded: queue health is reported in the admin ledger; nothing has '
           || 'reported under this key since 2026-09-29 and the queue is empty.')
  FROM operations.finding_types ft
 WHERE ft.id = f.finding_type_id AND ft.name = 'software_queue_stalled'
   AND f.condition_namespace = 'entity'
   AND f.condition_key = 'software_queue_stalled:software.activity'
   AND f.status IN ('open', 'acknowledged', 'investigating')
   AND f.last_detected_at < '2026-10-01';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0398_register_source_record_software_history"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
