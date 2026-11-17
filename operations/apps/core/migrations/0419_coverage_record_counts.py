"""Count Coverage source records without deriving unused lifecycle values."""

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION operations.read_coverage_source_record_counts(p_tenant bigint)
RETURNS TABLE(source_name text, record_count integer)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
    SELECT source.name::text, COUNT(*)::integer
    FROM operations.entity_observation_current observation
    JOIN operations.source_instances source_instance
      ON source_instance.tenant_id = observation.tenant_id
     AND source_instance.id = observation.source_instance_id
    JOIN operations.sources source ON source.id = source_instance.source_id
    WHERE observation.tenant_id = operations.current_tenant_id()
      AND observation.tenant_id = p_tenant
      AND (observation.entity_type LIKE 'agent.%'
           OR observation.entity_type IN ('vm.guest', 'cmdb.asset'))
    GROUP BY source.name;
$function$;

ALTER FUNCTION operations.read_coverage_source_record_counts(bigint)
    OWNER TO operations_view_owner;
REVOKE ALL ON FUNCTION operations.read_coverage_source_record_counts(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.read_coverage_source_record_counts(bigint)
    TO operations_app, operations_readonly;
"""

REVERSE_SQL = "DROP FUNCTION operations.read_coverage_source_record_counts(bigint);"


class Migration(migrations.Migration):
    dependencies = [("operations", "0418_page_scoped_hudu_evidence")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
