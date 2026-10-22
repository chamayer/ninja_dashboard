"""Check a client mapping decision's ``superseded_by`` reference at commit.

``decide_client_source_mapping_v1`` (migration 0201) supersedes the current
decision with the id of the decision it is about to insert, then inserts it.
The foreign key was checked immediately, so every change to a mapping that
already had a decision failed. The order cannot be reversed: the unique index
allows one current decision per source link, and the row check requires
``superseded_at`` and ``superseded_by_id`` together. Checking the reference at
commit keeps it enforced while letting the function's two statements land.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.client_source_mapping_decisions
    ALTER CONSTRAINT client_source_mapping_decisions_superseded_by_id_fkey
    DEFERRABLE INITIALLY DEFERRED;
"""

REVERSE_SQL = """
ALTER TABLE operations.client_source_mapping_decisions
    ALTER CONSTRAINT client_source_mapping_decisions_superseded_by_id_fkey
    NOT DEFERRABLE;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0338_ruon_process_monitors"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
