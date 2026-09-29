"""Return the claimed Job ID and fence through one constrained API."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION operations.jobs_claim_next_v2(
    p_tenant_id BIGINT,
    p_lane TEXT,
    p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_claim_token UUID;
BEGIN
    v_claim_token := operations.jobs_claim_next_v1(
        p_tenant_id, p_lane, p_worker_incarnation
    );
    IF v_claim_token IS NULL THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT job.id, v_claim_token
      FROM operations.operator_job_runs AS job
     WHERE job.tenant_id = p_tenant_id
       AND job.contract_version = 1
       AND job.claim_token = v_claim_token
       AND job.worker_incarnation = p_worker_incarnation
       AND job.status = 'running';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs claim result is unavailable or fenced';
    END IF;
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v2(BIGINT, TEXT, UUID)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v2(BIGINT, TEXT, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v2(BIGINT, TEXT, UUID)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0206_effective_client_mapping_decision_permissions"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
