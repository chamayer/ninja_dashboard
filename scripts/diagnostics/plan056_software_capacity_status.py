"""Bounded read-only publication resource, migration and fence verification."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
signal.alarm(20)
sys.path.insert(0,'/app')
from ingest import db
from ingest.config import settings
from shared.jobs_registry import definition
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    with db.transaction() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT EXISTS(SELECT 1 FROM operations.django_migrations WHERE app='operations' AND name='0417_software_automatic_request_fence')")
        print(json.dumps({'migration_0417_applied':cur.fetchone()[0]}),flush=True)
        cur.execute("SELECT pg_get_functiondef('operations.software_overview_inputs(bigint)'::regprocedure)")
        text=cur.fetchone()[0]
        print(json.dumps({'actor_fence': 'AND q.actor_id IS NOT NULL' in text,'old_delivery_filter':"q.trigger_kind <> 'dependency'" in text}),flush=True)
        cur.execute("SELECT r.id,r.status,r.wait_category,r.priority,v.metadata->'capacity_keys',r.definition_digest=%s,r.terminal_reason,r.started_at,r.completed_at FROM operations.operator_job_runs r JOIN operations.job_definition_versions v ON v.definition_key=r.job_key AND v.definition_digest=r.definition_digest WHERE r.tenant_id=1 AND r.job_key='software-overview' ORDER BY r.requested_at DESC LIMIT 3",(definition('software-overview').snapshot_digest(),))
        print(json.dumps({'overview_runs':cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT generation,published_at,window_expires_at,exposure_expires_at FROM operations.software_overview_current WHERE tenant_id=1")
        print(json.dumps({'publication':cur.fetchone()},default=str),flush=True)
        cur.execute("SELECT job_key,status,stage,started_at,wait_category,terminal_reason FROM operations.operator_job_runs WHERE tenant_id=1 AND status='running'")
        print(json.dumps({'running_jobs':cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid),round(extract(epoch FROM clock_timestamp()-query_start)), ARRAY(SELECT DISTINCT m[1] FROM regexp_matches(query,'operations[.][a-z_]+','g') m LIMIT 3) FROM pg_stat_activity WHERE datname=current_database() AND state='active' AND pid<>pg_backend_pid()")
        print(json.dumps({'activity':cur.fetchall()},default=str),flush=True)
finally:
    db.pool.close()
