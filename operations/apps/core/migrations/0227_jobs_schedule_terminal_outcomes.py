"""Project terminal Job results back to the owning durable schedule state."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION operations.jobs_record_schedule_terminal_outcome_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF NEW.tenant_id <> 1
       OR NEW.status NOT IN ('completed', 'failed', 'stalled', 'cancelled')
       OR OLD.status IS NOT DISTINCT FROM NEW.status
    THEN
        RETURN NEW;
    END IF;

    UPDATE operations.job_schedules AS schedule
       SET last_outcome = NEW.status
     WHERE schedule.tenant_id = NEW.tenant_id
       AND schedule.last_run_id = NEW.id;
    RETURN NEW;
END
$function$;

ALTER FUNCTION operations.jobs_record_schedule_terminal_outcome_v1()
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_record_schedule_terminal_outcome_v1()
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

CREATE TRIGGER jobs_record_schedule_terminal_outcome
    AFTER UPDATE OF status ON operations.operator_job_runs
    FOR EACH ROW EXECUTE FUNCTION operations.jobs_record_schedule_terminal_outcome_v1();

UPDATE operations.job_schedules AS schedule
   SET last_outcome = run.status
  FROM operations.operator_job_runs AS run
 WHERE schedule.tenant_id = run.tenant_id
   AND schedule.last_run_id = run.id
   AND run.status IN ('completed', 'failed', 'stalled', 'cancelled')
   AND schedule.last_outcome IS DISTINCT FROM run.status;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0226_jobs_runtime_diagnostics"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
