"""Retire unsupported operator release of uncertain Jobs resource holds."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
REVOKE EXECUTE ON FUNCTION operations.jobs_release_contained_claim_v1(BIGINT, UUID, INTEGER, TEXT)
FROM operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0234_fix_jobs_activity_relations_api"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
