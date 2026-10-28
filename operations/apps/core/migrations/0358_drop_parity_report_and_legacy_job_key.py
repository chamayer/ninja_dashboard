"""Drop the agent-compliance parity table and reference-feed history keys (PLAN-022 B1).

`operations.parity_report` was the cutover gate: the parity Job compared
legacy agent-compliance findings with Operations findings so the legacy
schema could be dropped. The schema and the Job were retired in Wave A, so
the table has no writer or purpose. Nothing has been written to it since
2026-10-07. It was exported before this migration (see PLAN-022).

`legacy_job_key` (migration 0269) kept each reference feed's pre-source-refresh
run history visible until the feed completed under its source-managed
schedule. All ten feeds have, so the Sources and Jobs pages no longer read
the key. The old runs stay in `operator_job_runs`; only the pointer goes.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DROP TABLE IF EXISTS operations.parity_report;

DELETE FROM operations.change_history_registry
 WHERE table_name = 'parity_report';

SELECT operations.begin_change(
    'source.retire_legacy_job_key',
    'PLAN-022: every reference feed has completed under its source-managed schedule, '
    || 'so the previous-schedule pointer is retired.',
    '{"migration": "0358_drop_parity_report_and_legacy_job_key"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0358', NULL, true);

UPDATE operations.source_instances
   SET config = config - 'legacy_job_key'
 WHERE config ? 'legacy_job_key';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0357_lifecycle_reported_state_fallback"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
