"""Expose a bounded expiry check to the existing Jobs scheduler.

No new schedule, queue or storage is introduced. Missing publication does not
start a bootstrap; owner-completion requests handle the initial build.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.software_overview_refresh_due(p_tenant bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software overview expiry context is invalid';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM operations.software_overview_current
         WHERE tenant_id = p_tenant
           AND (window_expires_at <= statement_timestamp()
                OR exposure_expires_at <= statement_timestamp())
    );
END
$fn$;
ALTER FUNCTION operations.software_overview_refresh_due(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.software_overview_refresh_due(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.software_overview_refresh_due(bigint) TO ninja_ingest;
"""

REVERSE_SQL = "DROP FUNCTION operations.software_overview_refresh_due(bigint);"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0407_software_overview_aggregate"),
    ]

    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
