"""Keep queued Jobs stages consistent with their durable wait evidence."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_default_waiting_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations AS $$
BEGIN
    IF NEW.contract_version = 1 AND NEW.status = 'queued' THEN
        IF NEW.wait_category IS NULL
           AND current_setting('operations.jobs_ready_promotion', TRUE) IS DISTINCT FROM 'on' THEN
            NEW.wait_category := 'capacity';
            NEW.wait_reason := 'Waiting for available Jobs capacity.';
            NEW.stage := 'Waiting for capacity';
            NEW.stage_detail := 'This work is ready when capacity is available.';
            NEW.stage_updated_at := now();
        ELSIF NEW.wait_category = 'dependency' THEN
            NEW.stage := 'Waiting for data';
            NEW.stage_detail := 'Required data is not ready.';
            NEW.stage_updated_at := now();
        ELSIF NEW.wait_category = 'workflow' THEN
            NEW.stage := 'Waiting for required work';
            NEW.stage_detail := 'Required workflow work is still running.';
            NEW.stage_updated_at := now();
        ELSIF NEW.wait_category = 'resource' THEN
            NEW.stage := 'Waiting for protected work';
            NEW.stage_detail := 'Another Job holds the protected data lock.';
            NEW.stage_updated_at := now();
        ELSIF NEW.wait_category = 'capacity' THEN
            NEW.stage := 'Waiting for capacity';
            NEW.stage_detail := 'This work is ready when capacity is available.';
            NEW.stage_updated_at := now();
        END IF;
    END IF;
    RETURN NEW;
END $$;

UPDATE operations.operator_job_runs
   SET stage = CASE wait_category
           WHEN 'dependency' THEN 'Waiting for data'
           WHEN 'workflow' THEN 'Waiting for required work'
           WHEN 'resource' THEN 'Waiting for protected work'
           WHEN 'capacity' THEN 'Waiting for capacity'
       END,
       stage_detail = CASE wait_category
           WHEN 'dependency' THEN 'Required data is not ready.'
           WHEN 'workflow' THEN 'Required workflow work is still running.'
           WHEN 'resource' THEN 'Another Job holds the protected data lock.'
           WHEN 'capacity' THEN 'This work is ready when capacity is available.'
       END,
       stage_updated_at = now()
 WHERE tenant_id = 1 AND status = 'queued'
   AND wait_category IN ('dependency', 'workflow', 'resource', 'capacity');

ALTER FUNCTION operations.jobs_default_waiting_v1() OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0255_jobs_dispatch_capacity_pools"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
