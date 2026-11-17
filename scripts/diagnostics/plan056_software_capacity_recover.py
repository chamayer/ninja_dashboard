"""Re-admit only outdated queued Software publication through governed APIs."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
signal.alarm(30)
sys.path.insert(0,'/app')
from ingest import db, operator_job_queue
from ingest.config import settings
from shared.jobs_registry import definition

job=definition('software-overview')
if job.capacity_keys != ('capacity:control',) or job.priority != 90:
    raise RuntimeError('New publication definition is not deployed')
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SET LOCAL lock_timeout='2s'")
        cur.execute("SELECT id FROM operations.users WHERE tenant_id=1 AND is_active AND is_superuser ORDER BY id LIMIT 1")
        actor=cur.fetchone()[0]
        cur.execute("SELECT id FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='software-overview' AND status='queued' AND definition_digest<>%s FOR UPDATE",(job.snapshot_digest(),))
        outdated=cur.fetchall()
        for (run,) in outdated:
            cur.execute("SELECT operations.jobs_cancel_v1(1,%s,%s,%s)",(run,actor,'User-authorized recovery: replace queued publication with reviewed control-capacity definition.'))
            print(json.dumps({'outdated_queued_cancel':str(run),'outcome':cur.fetchone()[0]}),flush=True)
        cur.execute("SELECT id FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='software-overview' AND definition_digest=%s AND status IN ('queued','running') ORDER BY requested_at DESC LIMIT 1",(job.snapshot_digest(),))
        active=cur.fetchone()
    if active:
        print(json.dumps({'existing_current_run':str(active[0])}),flush=True)
    else:
        run=operator_job_queue.request_system_job('software-overview','user-authorized-capacity-recovery')
        print(json.dumps({'requested':str(run),'capacity':list(job.capacity_keys),'priority':job.priority}),flush=True)
finally:
    db.pool.close()
