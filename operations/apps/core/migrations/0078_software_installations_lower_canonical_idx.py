"""Functional index on ``LOWER(canonical_name)`` for software installations.

Every case-insensitive lookup against ``software_installations_current`` (the
software detail page, rare-recent evaluator, decisions-queue join, findings
canonical link) was doing a parallel sequential scan over ~470k rows.
Adding a functional index turns those lookups into index scans.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE INDEX IF NOT EXISTS software_installations_current_lower_canonical_idx
    ON operations.software_installations_current (tenant_id, LOWER(canonical_name))
    WHERE deleted_at IS NULL AND stale_since IS NULL;
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS operations.software_installations_current_lower_canonical_idx;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0077_latest_reported_online_state"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
