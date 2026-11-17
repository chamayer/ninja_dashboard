"""Bound Hudu evidence expansion to explicitly selected observation IDs."""

from importlib import import_module

from django.db import migrations


# Keep the protected view's population, columns and relayed-card semantics.
# The ID predicate must be inside the materialized input, before JSON expansion.
SOURCE = import_module("apps.core.migrations.0150_hudu_computer_evidence_read_model").VIEW_SQL
BODY = SOURCE[SOURCE.index("WITH hudu_observation AS MATERIALIZED"):].strip().removesuffix(";")
PREDICATE = "WHERE observation.tenant_id = operations.current_tenant_id()"
assert BODY.count(PREDICATE) == 1
BODY = BODY.replace(
    PREDICATE,
    PREDICATE
    + "\n       AND observation.tenant_id = p_tenant"
    + "\n       AND observation.observation_id = ANY(p_observation_ids)",
    1,
)

FORWARD_SQL = f"""
CREATE FUNCTION operations.read_hudu_computer_inventory_evidence(
    p_tenant bigint, p_observation_ids uuid[]
)
RETURNS SETOF operations.v_hudu_computer_inventory_evidence_current
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
{BODY}
$function$;

ALTER FUNCTION operations.read_hudu_computer_inventory_evidence(bigint, uuid[])
    OWNER TO operations_view_owner;
REVOKE ALL ON FUNCTION operations.read_hudu_computer_inventory_evidence(bigint, uuid[])
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.read_hudu_computer_inventory_evidence(bigint, uuid[])
    TO operations_app, operations_readonly;
"""

REVERSE_SQL = """
DROP FUNCTION operations.read_hudu_computer_inventory_evidence(bigint, uuid[]);
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0417_software_automatic_request_fence")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
