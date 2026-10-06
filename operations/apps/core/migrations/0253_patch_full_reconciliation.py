"""Track the last successful full patch evaluation independently of run history."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.patch_evaluation_reconciliation (
    tenant_id BIGINT PRIMARY KEY REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    last_full_evaluated_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE operations.patch_evaluation_reconciliation OWNER TO operations_migrate;
REVOKE ALL ON operations.patch_evaluation_reconciliation
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.patch_evaluation_reconciliation TO ninja_ingest;
ALTER TABLE operations.patch_evaluation_reconciliation ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.patch_evaluation_reconciliation FORCE ROW LEVEL SECURITY;
CREATE POLICY patch_evaluation_reconciliation_tenant
    ON operations.patch_evaluation_reconciliation
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0252_jobs_interrupted_local_recovery")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
