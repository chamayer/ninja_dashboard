"""Apply immutable definition priority contracts at Jobs admission."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_apply_definition_priority_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_priority INTEGER;
BEGIN
    IF NEW.contract_version <> 1 THEN
        RETURN NEW;
    END IF;
    SELECT (definition_version.metadata ->> 'priority')::integer INTO v_priority
      FROM operations.job_definition_versions definition_version
     WHERE definition_version.definition_key = NEW.job_key
       AND definition_version.definition_digest = NEW.definition_digest;
    IF v_priority IS NULL OR v_priority NOT BETWEEN 0 AND 100 THEN
        RAISE EXCEPTION 'Jobs definition priority contract is invalid';
    END IF;
    NEW.priority := v_priority;
    RETURN NEW;
END
$function$;

ALTER FUNCTION operations.jobs_apply_definition_priority_v1() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_apply_definition_priority_v1()
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

CREATE TRIGGER jobs_apply_definition_priority
    BEFORE INSERT ON operations.operator_job_runs
    FOR EACH ROW EXECUTE FUNCTION operations.jobs_apply_definition_priority_v1();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0230_jobs_definition_timeout_contract"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
