"""Link new source-domain attempts to durable Jobs runs without backfilling fiction."""
from __future__ import annotations
from typing import ClassVar
from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.source_run_queue ADD COLUMN job_run_id UUID;
ALTER TABLE operations.source_run_queue ADD CONSTRAINT source_run_queue_job_run_reference
 FOREIGN KEY (job_run_id) REFERENCES operations.operator_job_runs(id) NOT VALID;
CREATE UNIQUE INDEX source_run_queue_job_run_once ON operations.source_run_queue(job_run_id) WHERE job_run_id IS NOT NULL;
ALTER TABLE operations.source_action_requests ADD COLUMN job_run_id UUID;
ALTER TABLE operations.source_action_requests ADD CONSTRAINT source_action_requests_job_run_reference
 FOREIGN KEY (job_run_id) REFERENCES operations.operator_job_runs(id) NOT VALID;
CREATE INDEX source_action_requests_job_run ON operations.source_action_requests(job_run_id) WHERE job_run_id IS NOT NULL;
"""
class Migration(migrations.Migration):
 dependencies: ClassVar[list[tuple[str,str]]]=[("operations","0214_jobs_timeout_containment")]
 operations: ClassVar[list]=[migrations.RunSQL(FORWARD_SQL,migrations.RunSQL.noop)]
