"""Make operator-managed condition episodes unique and upsertable."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM (
            SELECT tenant_id, condition_key, count(*) AS n
              FROM operations.findings
             WHERE condition_key > ''
               AND status IN ('open','acknowledged','investigating','suppressed')
             GROUP BY tenant_id, condition_key HAVING count(*) > 1
        ) duplicates
    ) OR EXISTS (
        SELECT 1 FROM (
            SELECT tenant_id, condition_key, count(*) AS n
              FROM operations.admin_findings
             WHERE status IN ('open','acknowledged','investigating','suppressed')
             GROUP BY tenant_id, condition_key HAVING count(*) > 1
        ) duplicates
    ) THEN
        RAISE EXCEPTION 'Cannot widen active condition uniqueness while duplicates exist';
    END IF;
END $$;
DROP INDEX operations.uq_findings_active_condition_key;
CREATE UNIQUE INDEX uq_findings_active_condition_key_scope
    ON operations.findings (tenant_id, condition_key)
    WHERE condition_key > '' AND status IN ('open','acknowledged','investigating','suppressed');
DROP INDEX operations.uq_admin_findings_active_condition_key;
CREATE UNIQUE INDEX uq_admin_findings_active_condition_key
    ON operations.admin_findings (tenant_id, condition_key)
    WHERE status IN ('open','acknowledged','investigating','suppressed');
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS operations.uq_findings_active_condition_key_scope;
CREATE UNIQUE INDEX uq_findings_active_condition_key
    ON operations.findings (tenant_id, condition_key)
    WHERE condition_key > '' AND status IN ('open','acknowledged');
DROP INDEX IF EXISTS operations.uq_admin_findings_active_condition_key;
CREATE UNIQUE INDEX uq_admin_findings_active_condition_key
    ON operations.admin_findings (tenant_id, condition_key)
    WHERE status IN ('open','acknowledged');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0167_reviewed_distinct_conditions"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
