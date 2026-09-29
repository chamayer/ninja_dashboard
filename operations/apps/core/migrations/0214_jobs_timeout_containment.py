"""Contain expired v1 Jobs claims without assuming a handler stopped."""
from __future__ import annotations
from typing import ClassVar
from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION operations.jobs_claim_next_v3(p_tenant_id BIGINT, p_lane TEXT, p_worker_incarnation UUID)
RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE v_claim RECORD;
BEGIN
 SELECT * INTO v_claim FROM operations.jobs_claim_next_v2(p_tenant_id,p_lane,p_worker_incarnation);
 IF NOT FOUND THEN RETURN; END IF;
 UPDATE operations.operator_job_runs AS job SET attempts=attempts+1, deadline_at=now()+INTERVAL '90 minutes'
  WHERE tenant_id=p_tenant_id AND id=v_claim.run_id AND contract_version=1
    AND claim_token=v_claim.claim_token AND worker_incarnation=p_worker_incarnation AND status='running'
 RETURNING job.job_key INTO job_key;
 IF NOT FOUND THEN RAISE EXCEPTION 'Jobs claim result is unavailable or fenced'; END IF;
 run_id:=v_claim.run_id; claim_token:=v_claim.claim_token; RETURN NEXT;
END $function$;

CREATE FUNCTION operations.jobs_contain_expired_v1(p_tenant_id BIGINT) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_count BIGINT;
BEGIN
 v_context_tenant:=NULLIF(current_setting('operations.tenant_id',TRUE),'')::bigint;
 IF v_context_tenant IS NULL OR v_context_tenant<>p_tenant_id OR p_tenant_id<>1 THEN
  RAISE EXCEPTION 'Jobs timeout context is invalid'; END IF;
 PERFORM set_config('operations.tenant_id',p_tenant_id::text,TRUE);
 WITH expired AS (
  UPDATE operations.operator_job_runs SET status='stalled',stage='Needs attention',
   stage_detail='Execution exceeded its safety deadline; resources remain contained.',
   stage_updated_at=now(),completed_at=now(),lease_expires_at=NULL,
   error='Execution exceeded the safety deadline. Verify the worker before retrying.',terminal_reason='timeout'
  WHERE tenant_id=p_tenant_id AND contract_version=1 AND status='running' AND deadline_at<=now()
  RETURNING id,claim_token
 ), claims AS (
  UPDATE operations.job_resource_claims c SET state='contained',release_reason='timeout contained'
   FROM expired WHERE c.tenant_id=p_tenant_id AND c.run_id=expired.id
    AND c.claim_token=expired.claim_token AND c.state='held' RETURNING c.run_id
 ), events AS (
  INSERT INTO operations.operator_job_events(tenant_id,job_id,event_type,stage,detail)
  SELECT p_tenant_id,id,'timeout','Needs attention','Execution exceeded its safety deadline; resources remain contained.' FROM expired
 ) SELECT count(*) INTO v_count FROM expired;
 RETURN v_count;
END $function$;
ALTER FUNCTION operations.jobs_claim_next_v3(BIGINT,TEXT,UUID) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_contain_expired_v1(BIGINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_contain_expired_v1(BIGINT) FROM PUBLIC,operations_app,ninja_ingest,operations_readonly,metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_contain_expired_v1(BIGINT) TO ninja_ingest;
"""
class Migration(migrations.Migration):
 dependencies: ClassVar[list[tuple[str,str]]]=[("operations","0213_jobs_cancellation_api")]
 operations: ClassVar[list]=[migrations.RunSQL(FORWARD_SQL,migrations.RunSQL.noop)]
