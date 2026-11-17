"""Recover Software inputs through existing governed Job admission only."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
signal.alarm(30)
sys.path.insert(0, '/app')
from ingest import db, operator_job_queue
from ingest.config import settings

allowed = {'computer-client-ownership','computer-client-ownership-sweep','software-classify-only','software-overview','intel-matcher','software-catalog'}
keys = sys.argv[1:]
cancel_duplicate = keys == ['--cancel-duplicate-matcher']
if not cancel_duplicate and (not keys or not set(keys) <= allowed):
    raise SystemExit('Unapproved job key')
db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    if cancel_duplicate:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id='1'")
            cur.execute("SET LOCAL statement_timeout='8s'")
            cur.execute("SELECT id FROM operations.users WHERE tenant_id=1 AND is_active AND is_superuser ORDER BY id LIMIT 1")
            actor=cur.fetchone()[0]
            cur.execute("SELECT id FROM operations.operator_job_runs WHERE tenant_id=1 AND id='131df020-f757-4b5f-98c3-55b67b7fdfc9' AND job_key='intel-matcher' AND status='queued' AND EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='intel-matcher' AND status='running')")
            row=cur.fetchone()
            if row:
                cur.execute("SELECT operations.jobs_cancel_v1(1,%s,%s,%s)",(row[0],actor,'Avoid duplicate recovery while original matcher is still executing; retain actual completion evidence.'))
                print(json.dumps({'duplicate_matcher_stop':cur.fetchone()[0]}),flush=True)
    else:
        for key in keys:
            run = operator_job_queue.request_system_job(key, 'user-authorized-software-emergency-20261113')
            print(json.dumps({'requested':key,'run_id':str(run)}),flush=True)
finally:
    db.pool.close()
