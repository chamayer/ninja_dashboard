"""Make broad software reclassification targets resumable by device batch."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.software_reclassification_targets
    ADD COLUMN IF NOT EXISTS cursor_device_id UUID;

COMMENT ON COLUMN operations.software_reclassification_targets.cursor_device_id IS
    'Highest device identity durably processed for this targeted software reclassification.';

CREATE TABLE IF NOT EXISTS operations.software_full_reclassification_state (
    tenant_id BIGINT PRIMARY KEY REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    cursor_device_id UUID,
    in_progress BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE operations.software_full_reclassification_state OWNER TO operations_migrate;
REVOKE ALL ON operations.software_full_reclassification_state
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.software_full_reclassification_state TO ninja_ingest;
ALTER TABLE operations.software_full_reclassification_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_full_reclassification_state FORCE ROW LEVEL SECURITY;
CREATE POLICY software_full_reclassification_state_tenant
    ON operations.software_full_reclassification_state
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0276_jobs_retry_current_definition"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
