"""Durable, tenant-scoped queue for operator-requested Jobs runs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE TABLE operations.operator_job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    job_key TEXT NOT NULL,
    batch_id UUID,
    requested_by_id INTEGER REFERENCES operations.users(id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'stalled', 'cancelled')),
    attempts SMALLINT NOT NULL DEFAULT 0,
    rows_touched INTEGER,
    run_log_kind TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX uq_operator_job_runs_active
    ON operations.operator_job_runs (tenant_id, job_key)
    WHERE status IN ('queued', 'running');
CREATE INDEX idx_operator_job_runs_queue
    ON operations.operator_job_runs (tenant_id, requested_at, id)
    WHERE status = 'queued';
CREATE INDEX idx_operator_job_runs_status
    ON operations.operator_job_runs (tenant_id, status, requested_at DESC);
CREATE INDEX idx_operator_job_runs_batch
    ON operations.operator_job_runs (tenant_id, batch_id, requested_at, id)
    WHERE batch_id IS NOT NULL;

ALTER TABLE operations.operator_job_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.operator_job_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.operator_job_runs
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
ALTER TABLE operations.operator_job_runs OWNER TO operations_migrate;
REVOKE ALL ON operations.operator_job_runs
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT, INSERT ON operations.operator_job_runs TO operations_app;
GRANT SELECT, UPDATE ON operations.operator_job_runs TO ninja_ingest;

INSERT INTO operations.queue_registry (
    queue_key, queue_type, table_name, owner, enabled,
    max_pending_age_m, max_failure_count, max_depth, description
) VALUES (
    'operator.jobs', 'processing', 'operations.operator_job_runs', 'operations.jobs', TRUE,
    15, 1, 25, 'Operator-requested collection and evaluation work'
)
ON CONFLICT (queue_key) DO UPDATE SET
    table_name = EXCLUDED.table_name, owner = EXCLUDED.owner, enabled = TRUE,
    max_pending_age_m = EXCLUDED.max_pending_age_m,
    max_failure_count = EXCLUDED.max_failure_count,
    max_depth = EXCLUDED.max_depth,
    description = EXCLUDED.description;

UPDATE operations.finding_types
   SET description = 'A processing queue is delayed, stalled, or has failed work that needs review.'
 WHERE name = 'software_queue_stalled';
"""

REVERSE_SQL = "DROP TABLE IF EXISTS operations.operator_job_runs;"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0177_seed_patching_inactive_label")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
