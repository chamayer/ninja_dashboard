"""Allow the effective client-mapping projection to read its link source."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
GRANT SELECT ON operations.v_client_source_link TO operations_view_owner;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0204_activate_committed_condition_policies")
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
