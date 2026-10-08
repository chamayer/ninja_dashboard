"""Keep stopped Jobs from retaining execution capacity."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
/* A contained claim protects uncertain data effects; it is never a live worker.
 * Capacity and legacy lane claims describe live execution only, so retain the
 * data boundary but release those claims whenever work is contained. */
CREATE OR REPLACE FUNCTION operations.jobs_release_contained_capacity_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF NEW.state = 'contained' AND (
        NEW.resource_template LIKE 'capacity:%'
        OR NEW.resource_template LIKE 'lane:%'
        OR NEW.resource_template IN ('execution:deployment', 'execution:emergency-child')
    ) THEN
        NEW.state := 'released';
        NEW.released_at := COALESCE(NEW.released_at, now());
        NEW.release_reason := 'Execution capacity released after work stopped; any affected data boundary remains protected.';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS jobs_release_contained_capacity_before_write
    ON operations.job_resource_claims;
CREATE TRIGGER jobs_release_contained_capacity_before_write
BEFORE INSERT OR UPDATE OF state, resource_template ON operations.job_resource_claims
FOR EACH ROW EXECUTE FUNCTION operations.jobs_release_contained_capacity_v1();

WITH released AS (
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(),
           release_reason = 'Execution capacity released after work stopped; any affected data boundary remains protected.'
     WHERE state = 'contained'
       AND (
           resource_template LIKE 'capacity:%'
           OR resource_template LIKE 'lane:%'
           OR resource_template IN ('execution:deployment', 'execution:emergency-child')
       )
 RETURNING tenant_id, run_id
)
INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
SELECT DISTINCT tenant_id, run_id, 'capacity_released', 'Needs attention',
       'The process stopped, so its execution capacity was released. Any affected data boundary remains protected.'
  FROM released;

ALTER FUNCTION operations.jobs_release_contained_capacity_v1() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_release_contained_capacity_v1()
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0270_retire_source_demand_runs"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
