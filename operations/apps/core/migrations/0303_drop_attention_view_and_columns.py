"""Remove what migration 0301 replaced: the attention columns, the live view and their triggers.

``finding_state`` (0301, 0302) is now the only stored state and the Issues page reads it. Dropped
here: the ``finding_states`` view and ``finding_live_attention`` (0298-0300), the
``findings.attention`` / ``attention_at`` columns, their index, the status-change trigger and
functions (0297), and the old drift table. Nothing reads or writes them any more.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DROP VIEW IF EXISTS operations.finding_states;
DROP FUNCTION IF EXISTS operations.finding_live_attention(
    text, timestamptz, text, timestamptz, integer);
DROP FUNCTION IF EXISTS operations.finding_live_attention(text, timestamptz, text, timestamptz);
DROP TRIGGER IF EXISTS findings_attention_after_update ON operations.findings;
DROP TRIGGER IF EXISTS findings_attention_after_insert ON operations.findings;
DROP FUNCTION IF EXISTS operations.refresh_attention_after_status_change();
DROP FUNCTION IF EXISTS operations.refresh_finding_attention(uuid[]);
DROP FUNCTION IF EXISTS operations.compute_finding_attention(uuid[]);
DROP TABLE IF EXISTS operations.finding_attention_drift;
DROP INDEX IF EXISTS operations.idx_findings_attention_active;
ALTER TABLE operations.findings DROP COLUMN IF EXISTS attention_at,
                                DROP COLUMN IF EXISTS attention;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0302_finding_state_skip_unchanged"),
    ]

    operations: ClassVar[list] = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)],
            state_operations=[
                migrations.DeleteModel(name="FindingState"),
                migrations.RemoveField(model_name="finding", name="attention"),
                migrations.RemoveField(model_name="finding", name="attention_at"),
            ],
        ),
    ]
