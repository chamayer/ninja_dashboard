"""The naming role may call the functions its reads depend on (fix for 0328).

``operations_naming`` reads through row-level security policies and views
that call ``operations.current_tenant_id()`` and similar helpers; 0328 granted
only the naming functions, so the first production reconciliation failed with
"permission denied for function current_tenant_id". The role cannot log in and
is reached only through ``write_computer_names``, whose body is fixed, so it
gets EXECUTE on the schema's functions.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA operations TO operations_naming;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0330_computer_name_differs_in_source"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
