"""Stop taking one advisory lock per finding in participant reconciliation.

``reconcile_condition_participants`` (0166) serialized writers of one finding
with a transaction advisory lock. Since 0365 every write to condition
assessments and participants must already hold the exclusive tenant guard, so
that lock no longer adds anything. It did start to cost: the guard check reads
``pg_locks``, whose cost grows with every lock held in the database, and the
evaluator took one such lock per finding in its single transaction. From 0.132.0
each guarded write slowed as a run went on, and evaluation runs grew from about
4 to about 30 minutes while holding the guard.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_integrity = importlib.import_module("apps.core.migrations.0166_condition_assessment_integrity")

_LOCK = """    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_tenant_id::text || ':' || p_row_kind || ':' || p_finding_id::text, 0));
"""


def _function() -> str:
    sql = _integrity.FORWARD_SQL
    start = sql.index("CREATE OR REPLACE FUNCTION operations.reconcile_condition_participants(")
    end = sql.index("$$;", start) + len("$$;")
    return sql[start:end] + "\n"


def _forward_sql() -> str:
    body = _function()
    assert body.count(_LOCK) == 1
    return body.replace(_LOCK, "")


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0393_close_superseded_software_failures"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(_forward_sql(), _function())]
