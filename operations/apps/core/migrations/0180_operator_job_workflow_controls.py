"""Add lanes, worker heartbeats, and an immutable event journal to Jobs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
ALTER TABLE operations.operator_job_runs
    ADD COLUMN lane TEXT NOT NULL DEFAULT 'evaluation',
    ADD COLUMN priority SMALLINT NOT NULL DEFAULT 50,
    ADD COLUMN heartbeat_at TIMESTAMPTZ;

UPDATE operations.operator_job_runs
   SET lane = CASE
       WHEN job_key IN ('patches', 'agent-observations', 'documentation-observations') THEN 'collection'
       WHEN job_key LIKE 'intel-%' THEN 'intelligence'
       WHEN job_key IN ('notifications-dispatch', 'notifications-digest', 'retention-history') THEN 'service'
       ELSE 'evaluation'
   END,
       heartbeat_at = COALESCE(stage_updated_at, started_at, requested_at);

CREATE INDEX idx_operator_job_runs_lane_queue
    ON operations.operator_job_runs (tenant_id, lane, priority DESC, requested_at, id)
    WHERE status = 'queued';
CREATE INDEX idx_operator_job_runs_heartbeat
    ON operations.operator_job_runs (tenant_id, heartbeat_at)
    WHERE status = 'running';

CREATE TABLE operations.operator_job_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    job_id UUID NOT NULL REFERENCES operations.operator_job_runs(id) ON DELETE CASCADE,
    event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_operator_job_events_job
    ON operations.operator_job_events (tenant_id, job_id, event_at DESC, id DESC);
ALTER TABLE operations.operator_job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.operator_job_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.operator_job_events
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
ALTER TABLE operations.operator_job_events OWNER TO operations_migrate;
REVOKE ALL ON operations.operator_job_events
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.operator_job_events TO operations_app;
GRANT SELECT, INSERT, UPDATE ON operations.operator_job_runs TO ninja_ingest;
GRANT INSERT ON operations.operator_job_events TO ninja_ingest;
"""

REVERSE_SQL = """
DROP TABLE IF EXISTS operations.operator_job_events;
DROP INDEX IF EXISTS operations.idx_operator_job_runs_heartbeat;
DROP INDEX IF EXISTS operations.idx_operator_job_runs_lane_queue;
ALTER TABLE operations.operator_job_runs
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS priority,
    DROP COLUMN IF EXISTS lane;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0179_add_operator_job_progress"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
