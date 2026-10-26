"""Fence software reclassification target acknowledgments by generation.

PLAN-017 U04 (PLAN-019 Step 2): a producer that records a change for a title
already pending coalesces into that row. If the findings run had captured the
row before the change, its acknowledgment consumed the newer demand too, and
the title stayed stale until the next whole-fleet run. Every producer now
increments ``generation`` on conflict, and the findings run acknowledges only
the generation it captured, so a newer change leaves the row pending.

Adding a column with a constant default rewrites no rows.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.software_reclassification_targets
    ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 1;

COMMENT ON COLUMN operations.software_reclassification_targets.generation IS
    'Incremented each time a producer coalesces a new change into this pending row; '
    'the findings run acknowledges only the generation it captured.';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0348_observation_domain"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
