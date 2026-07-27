"""Give ``findings.subject_layer`` a DB-level ``DEFAULT ''``.

The column was created NOT NULL without a default. The Django model
declares ``default=""`` at the ORM layer, but raw-SQL INSERTs from
``ingest/evaluator.py`` and friends don't pass the ORM, so they hit
"null value in column subject_layer violates not-null constraint".

Setting the default at the DB level fixes every path — existing and
future — without requiring every writer to be updated.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.findings
    ALTER COLUMN subject_layer SET DEFAULT '';
UPDATE operations.findings SET subject_layer = '' WHERE subject_layer IS NULL;
"""

REVERSE_SQL = """
ALTER TABLE operations.findings
    ALTER COLUMN subject_layer DROP DEFAULT;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0084_known_malicious_hint_finding_type"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
