"""Unique (tenant_id, id) on findings, for tenant-safe composite FKs (PLAN-003 M1).

Later migrations reference findings by (tenant_id, finding_id) so a related row
can never point at another tenant's finding. ``id`` is already unique, so this
index cannot fail on existing data. Built concurrently so producers keep
writing; the migration is therefore not atomic. 0363 refuses to run if a failed
build left the index invalid.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0361_source_record_reported_contact"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_findings_tenant_id "
            "ON operations.findings (tenant_id, id)",
            "DROP INDEX CONCURRENTLY IF EXISTS operations.uq_findings_tenant_id",
        ),
    ]
