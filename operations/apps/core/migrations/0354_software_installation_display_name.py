"""Keep Ninja's source spelling alongside the software matching key."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS display_name text NOT NULL DEFAULT '';
"""

REVERSE_SQL = """
ALTER TABLE operations.software_installations_current
    DROP COLUMN IF EXISTS display_name;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0353_close_cross_ledger_issue_duplicates"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
