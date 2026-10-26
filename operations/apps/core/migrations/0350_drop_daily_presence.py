"""Drop Ninja daily presence (PLAN-022 A1; PLAN-019 F09 decision).

The user decided on 2026-10-26 that no source keeps daily presence. It was
the stand-in for the legacy daily active-device trend (ADR 0010), which has no
reader: nothing in the repository reads the table or its only view, and the
writer was removed in the same change. Presence over time becomes part of the
ADR 0045 significant-change trail. The table was exported before this
migration (see PLAN-022). The view is its only dependent object.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DROP VIEW IF EXISTS operations.ninja_device_seen_daily_shadow;
DROP TABLE IF EXISTS operations.source_record_seen_daily;

DELETE FROM operations.change_history_registry
 WHERE table_name = 'source_record_seen_daily';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0349_software_target_generation"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
