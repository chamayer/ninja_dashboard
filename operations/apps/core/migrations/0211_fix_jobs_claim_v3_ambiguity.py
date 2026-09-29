"""Fix the v1 worker claim function's output-column ambiguity."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION operations.jobs_claim_next_v3(
    p_tenant_id BIGINT, p_lane TEXT, p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE v_claim RECORD;
BEGIN
    SELECT * INTO v_claim FROM operations.jobs_claim_next_v2(p_tenant_id, p_lane, p_worker_incarnation);
    IF NOT FOUND THEN RETURN; END IF;
    UPDATE operations.operator_job_runs AS job
       SET attempts = job.attempts + 1
     WHERE job.tenant_id = p_tenant_id AND job.id = v_claim.run_id
       AND job.contract_version = 1 AND job.claim_token = v_claim.claim_token
       AND job.worker_incarnation = p_worker_incarnation AND job.status = 'running'
     RETURNING job.job_key INTO job_key;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs claim result is unavailable or fenced'; END IF;
    run_id := v_claim.run_id;
    claim_token := v_claim.claim_token;
    RETURN NEXT;
END
$function$;
ALTER FUNCTION operations.jobs_claim_next_v3(BIGINT, TEXT, UUID) OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0210_jobs_schedule_reconciliation_api")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
