"""Grant the software exposure view owner access to its condition tables."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
GRANT SELECT ON operations.condition_assessments,
    operations.condition_policy_versions
TO operations_view_owner;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0169_align_condition_reviewer_ids"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
