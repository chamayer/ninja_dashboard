"""Reassess source records after adding independent MAC validity results."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

REASSESS_SQL = r"""
SELECT operations.source_record_enqueue(tenant_id, 'source_record', id)
  FROM operations.source_record_subjects
 WHERE subject_kind = 'record';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0383_entity_link_divergence_finding"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(REASSESS_SQL, migrations.RunSQL.noop),
    ]
