"""Apply immutable definition timeout contracts when claiming Jobs work."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_claim_next_v4(
    p_tenant_id BIGINT, p_lane TEXT, p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_claim RECORD; v_timeout_minutes INTEGER;
BEGIN
    SELECT * INTO v_claim
      FROM operations.jobs_claim_next_v3(p_tenant_id, p_lane, p_worker_incarnation);
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT COALESCE((definition_version.metadata ->> 'timeout_minutes')::integer, 90)
      INTO v_timeout_minutes
      FROM operations.operator_job_runs run
      JOIN operations.job_definition_versions definition_version
        ON definition_version.definition_key = run.job_key
       AND definition_version.definition_digest = run.definition_digest
     WHERE run.tenant_id = p_tenant_id AND run.id = v_claim.run_id;
    IF v_timeout_minutes IS NULL OR v_timeout_minutes NOT BETWEEN 1 AND 1440 THEN
        RAISE EXCEPTION 'Jobs definition timeout contract is invalid';
    END IF;
    UPDATE operations.operator_job_runs run
       SET deadline_at = now() + make_interval(mins => v_timeout_minutes)
     WHERE run.tenant_id = p_tenant_id AND run.id = v_claim.run_id
       AND run.contract_version = 1 AND run.status = 'running'
       AND run.claim_token = v_claim.claim_token
       AND run.worker_incarnation = p_worker_incarnation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs timeout contract is unavailable or fenced';
    END IF;
    run_id := v_claim.run_id;
    claim_token := v_claim.claim_token;
    job_key := v_claim.job_key;
    RETURN NEXT;
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v4(BIGINT, TEXT, UUID) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v4(BIGINT, TEXT, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v4(BIGINT, TEXT, UUID) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0229_jobs_health_measurements"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
