"""Allow the effective client-mapping projection to read mapping decisions."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
GRANT SELECT ON operations.client_source_mapping_decisions TO operations_view_owner;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0205_effective_client_mapping_view_permissions")
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
