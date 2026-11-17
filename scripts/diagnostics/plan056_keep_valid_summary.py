"""Approved emergency reader fix; retain every real input/security/expiry gate."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0,'/app')
signal.alarm(20)
from ingest import db
from ingest.config import settings

old="status = 'queued' AND wait_category = 'dependency'\n                    AND "
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SET LOCAL lock_timeout='2s'")
        cur.execute("SELECT pg_get_functiondef('operations.read_software_overview(bigint,uuid)'::regprocedure)")
        sql=cur.fetchone()[0]
        if sql.count(old)!=1:
            raise RuntimeError('Reader source mismatch')
        cur.execute(sql.replace(old,'',1))
        cur.execute("SELECT operations.read_software_overview(1,NULL)")
        payload=cur.fetchone()[0]
        print(json.dumps({'reader_fix_applied':True,'state':payload.get('state'),'reason':payload.get('reason'),'has_data':bool(payload.get('data'))}),flush=True)
finally:
    db.pool.close()
