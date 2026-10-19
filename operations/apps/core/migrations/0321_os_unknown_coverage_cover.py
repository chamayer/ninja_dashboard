"""The unknown-OS coverage finding is covered when no source reports the Computer.

0320 registered ``os_unknown_coverage`` without a cover rule, so it stayed in
view on Computers no source reports, where ``missing_required_platform`` (the
finding it stands in for) is covered. It now follows the same rule. The open
findings' state is refreshed here; ``compute_finding_state`` reads the rule
live from then on.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'finding_type.cover',
    'os_unknown_coverage stands in for missing_required_platform and is covered like it.',
    '{"migration": "0321_os_unknown_coverage_cover"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0321', NULL, true);

UPDATE operations.finding_types
   SET covered_by = '["device_missing_from_source"]'::jsonb,
       cover_note = 'Coverage cannot be assessed on a computer no source reports.'
 WHERE name = 'os_unknown_coverage';

SELECT set_config('operations.tenant_id', '1', TRUE);
SELECT operations.refresh_finding_state((
    SELECT array_agg(f.id)
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE ft.name = 'os_unknown_coverage'
       AND f.status IN ('open', 'acknowledged', 'investigating')));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0320_os_unknown_coverage"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
