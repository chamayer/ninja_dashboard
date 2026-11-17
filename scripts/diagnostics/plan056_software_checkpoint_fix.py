"""Separately approved fix: exclude input attempts that never executed."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0,"/app")
signal.alarm(20)
from ingest import db
from ingest.config import settings

old = "WHERE r.tenant_id = p_tenant AND r.status <> 'queued' "
new = old + "AND (r.started_at IS NOT NULL OR r.status = 'completed') "
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SET LOCAL lock_timeout='2s'")
        cur.execute("SELECT pg_get_functiondef('operations.software_overview_inputs(bigint)'::regprocedure)")
        sql = cur.fetchone()[0]
        if sql.count(old)!=1 or "AND device.deleted_at IS NULL" not in sql:
            raise RuntimeError("Input checkpoint source mismatch")
        if sys.argv[1:]==['--apply']:
            cur.execute(sql.replace(old,new,1))
        cur.execute("SELECT operations.software_overview_inputs(1)")
        inputs=cur.fetchone()[0]
        print(json.dumps({'applied':sys.argv[1:]==['--apply'],'owners_ready':{k:v.get('ready') for k,v in inputs['owners'].items()},'ownership_pending':inputs.get('ownership_pending'),'classification_pending':inputs.get('classification_pending')}),flush=True)
finally:
    db.pool.close()
