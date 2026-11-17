"""User-authorized bounded recovery: stop competing assessment, retain guards."""
import json
import logging
import signal
import sys
import time

logging.disable(logging.CRITICAL)
signal.alarm(720)
sys.path.insert(0,'/app')
from ingest import db, operator_job_queue
from ingest.config import settings
db.init(settings.postgres_dsn,min_size=1,max_size=2)
try:
    with db.pool.connection() as leader:
        leader.autocommit=True
        with leader.cursor() as gate:
            gate.execute("SET statement_timeout='8s'")
            gate.execute('SELECT operations.jobs_try_schedule_leader()')
            if not gate.fetchone()[0]:
                raise RuntimeError('Scheduler lease busy')
            print(json.dumps({'recovery_window_started':True}),flush=True)
            try:
                with db.transaction() as cur:
                    cur.execute("SET LOCAL operations.tenant_id='1'")
                    cur.execute("SET LOCAL statement_timeout='8s'")
                    cur.execute("SELECT id FROM operations.users WHERE tenant_id=1 AND is_active AND is_superuser ORDER BY id LIMIT 1")
                    actor=cur.fetchone()[0]
                    cur.execute('SELECT operations.software_overview_inputs(1)')
                    allowed=list(cur.fetchone()[0]['owners'])+['software-overview']
                    cur.execute("SELECT id,job_key FROM operations.operator_job_runs WHERE tenant_id=1 AND NOT (job_key=ANY(%s)) AND status IN ('queued','running') AND cancellation_requested_at IS NULL",(allowed,))
                    for run,key in cur.fetchall():
                        cur.execute("SELECT operations.jobs_cancel_v1(1,%s,%s,%s)",(run,actor,'User-authorized Software recovery: let required platform input complete.'))
                        print(json.dumps({'competing_job':key,'stop':cur.fetchone()[0]}),flush=True)
                deadline=time.monotonic()+600
                while time.monotonic()<deadline:
                    with db.transaction() as cur:
                        cur.execute("SET LOCAL operations.tenant_id='1'")
                        cur.execute("SET LOCAL statement_timeout='8s'")
                        cur.execute('SELECT operations.software_overview_inputs(1)')
                        inputs=cur.fetchone()[0]
                        pending=[k for k,v in inputs['owners'].items() if not v.get('ready')]
                        print(json.dumps({'owners_not_ready':pending,'active_inputs':len(inputs.get('active',[])),'classification_pending':inputs.get('classification_pending')}),flush=True)
                        cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key IN ('software-classify','software-classify-only','software-classify-full') AND status IN ('queued','running'))")
                        classification_active=cur.fetchone()[0]
                        cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='platform-evaluate' AND status='running' AND terminal_reason IS DISTINCT FROM 'handler_completed')")
                        platform_active=cur.fetchone()[0]
                        cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key=ANY(%s) AND status='running' AND terminal_reason IS DISTINCT FROM 'handler_completed')",(allowed,))
                        required_active=cur.fetchone()[0]
                        cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key IN ('computer-client-ownership','computer-client-ownership-sweep') AND status IN ('queued','running'))")
                        ownership_active=cur.fetchone()[0]
                    if inputs.get('classification_pending') and not classification_active:
                        run=operator_job_queue.request_system_job('software-classify-only','user-authorized-input-recovery')
                        print(json.dumps({'classifier_requested':str(run)}),flush=True)
                    if inputs.get('ownership_pending') and not ownership_active:
                        run=operator_job_queue.request_system_job('computer-client-ownership','user-authorized-input-recovery')
                        print(json.dumps({'ownership_requested':str(run)}),flush=True)
                    if not pending and not inputs.get('active') and not inputs.get('classification_pending') and not inputs.get('ownership_pending') and not platform_active and not required_active:
                        print(json.dumps({'inputs_ready_for_deployment':True}),flush=True)
                        time.sleep(90)
                        break
                    time.sleep(8)
            finally:
                gate.execute('SELECT operations.jobs_release_schedule_leader()')
                print(json.dumps({'scheduler_resumed':gate.fetchone()[0]}),flush=True)
finally:
    db.pool.close()
