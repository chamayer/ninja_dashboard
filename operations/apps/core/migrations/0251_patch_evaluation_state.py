"""Track the device state last consumed by incremental patch evaluation."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.patch_evaluation_state (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    device_id UUID NOT NULL,
    state_digest TEXT NOT NULL CHECK (state_digest ~ '^[0-9a-f]{32}$'),
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id)
);
ALTER TABLE operations.patch_evaluation_state OWNER TO operations_migrate;
REVOKE ALL ON operations.patch_evaluation_state
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.patch_evaluation_state TO ninja_ingest;
ALTER TABLE operations.patch_evaluation_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.patch_evaluation_state FORCE ROW LEVEL SECURITY;
CREATE POLICY patch_evaluation_state_tenant ON operations.patch_evaluation_state
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0250_software_reclassification_targets"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
