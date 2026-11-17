"""Bounded read-only Software job failure evidence; no payload values."""
import json
import logging
import re
import signal
import sys

logging.disable(logging.CRITICAL)
signal.alarm(25)
sys.path.insert(0, '/app')
from ingest import db
from ingest.config import settings

db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.transaction() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT id,status,terminal_reason,requested_at,started_at,completed_at,error,stage FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='software-overview' ORDER BY requested_at DESC LIMIT 5")
        for row in cur.fetchall():
            error = row[6] or ''
            known = re.findall(r'\b(?:[A-Z][A-Za-z]*(?:Error|Exception|Detected|Violation|Timeout)|deadlock detected|statement timeout|permission denied|input_changed|worker_shutdown|claim_lost)\b', error)
            known += [message for message in ('Software overview preparation inputs are pending or failed', 'Software inputs changed during preparation', 'Software overview inputs are pending or failed', 'Software overview inputs changed during publication', 'Software overview prerequisite is incomplete', 'Software overview publisher was revoked or expired') if message in error]
            print(json.dumps({'run':str(row[0]),'status':row[1],'reason':row[2], 'requested':row[3], 'started':row[4], 'completed':row[5], 'error_classes':known,'stage':row[7]},default=str),flush=True)
        cur.execute("SELECT generation,computed_at,published_at,exposure_expires_at,window_expires_at,input_watermarks->>'publication_run_id' FROM operations.software_overview_current WHERE tenant_id=1")
        print(json.dumps({'publication':cur.fetchone()},default=str),flush=True)
        cur.execute('SELECT operations.software_overview_inputs(1)')
        inputs=cur.fetchone()[0]
        print(json.dumps({'ownership_pending':inputs.get('ownership_pending'),'classification_pending':inputs.get('classification_pending'),'active_count':len(inputs.get('active',[])), 'owners_ready':{k:v.get('ready') for k,v in inputs.get('owners',{}).items()}}),flush=True)
        cur.execute("SELECT count(*) FROM operations.software_reclassification_targets WHERE tenant_id=1 AND consumed_at IS NULL")
        print(json.dumps({'targets':cur.fetchone()[0]}),flush=True)
        cur.execute("SELECT job_key,status,terminal_reason,stage,requested_at,started_at,completed_at FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key IN ('software-classify-only','software-classify','software-classify-full','computer-client-ownership-sweep') ORDER BY requested_at DESC LIMIT 8")
        print(json.dumps({'input_jobs':cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT job_key,status,stage FROM operations.operator_job_runs WHERE tenant_id=1 AND status='running'")
        print(json.dumps({'running':cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid),round(extract(epoch FROM clock_timestamp()-query_start)), ARRAY(SELECT DISTINCT m[1] FROM regexp_matches(query,'operations[.][a-z_]+','g') m LIMIT 3) FROM pg_stat_activity WHERE datname=current_database() AND state='active' AND pid<>pg_backend_pid()")
        print(json.dumps({'activity':cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT count(*),count(*) FILTER (WHERE updated_at >= '2026-11-13 16:00:49+00') FROM operations.computer_client_ownership WHERE tenant_id=1")
        print(json.dumps({'ownership_rows_and_recent_updates':cur.fetchone()}),flush=True)
finally:
    db.pool.close()
