"""Make source-domain Job links tenant-safe and enforce tenant isolation."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
ALTER TABLE operations.source_run_queue ADD COLUMN tenant_id BIGINT;
UPDATE operations.source_run_queue SET tenant_id = 1 WHERE tenant_id IS NULL;
ALTER TABLE operations.source_run_queue ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE operations.source_run_queue
    ADD CONSTRAINT source_run_queue_tenant_reference
    FOREIGN KEY (tenant_id) REFERENCES operations.tenants(id);
ALTER TABLE operations.source_run_queue
    ADD CONSTRAINT source_run_queue_current_tenant CHECK (tenant_id = 1);

ALTER TABLE operations.source_run_queue
    DROP CONSTRAINT source_run_queue_job_run_reference;
ALTER TABLE operations.source_run_queue
    ADD CONSTRAINT source_run_queue_job_run_reference
    FOREIGN KEY (tenant_id, job_run_id)
    REFERENCES operations.operator_job_runs(tenant_id, id) NOT VALID;
ALTER TABLE operations.source_run_queue
    VALIDATE CONSTRAINT source_run_queue_job_run_reference;

ALTER TABLE operations.source_action_requests
    DROP CONSTRAINT source_action_requests_job_run_reference;
ALTER TABLE operations.source_action_requests
    ADD CONSTRAINT source_action_requests_job_run_reference
    FOREIGN KEY (tenant_id, job_run_id)
    REFERENCES operations.operator_job_runs(tenant_id, id) NOT VALID;
ALTER TABLE operations.source_action_requests
    VALIDATE CONSTRAINT source_action_requests_job_run_reference;

ALTER TABLE operations.source_run_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_run_queue FORCE ROW LEVEL SECURITY;
CREATE POLICY source_run_queue_tenant_isolation
ON operations.source_run_queue
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

ALTER TABLE operations.source_action_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_action_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY source_action_requests_tenant_isolation
ON operations.source_action_requests
USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0217_jobs_cooperative_cancellation"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
