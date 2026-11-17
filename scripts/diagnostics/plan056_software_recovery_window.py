"""User-authorized bounded recovery window using existing Jobs controls."""
import json
import logging
import signal
import sys
import time

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/app")
signal.alarm(205)
from ingest import db, operator_job_queue
from ingest.config import settings

allowed = {"software-overview", "software-classify-only", "software-classify-full", "software-classify", "computer-client-ownership", "computer-client-ownership-sweep", "platform-evaluate"}
db.init(settings.postgres_dsn, min_size=1, max_size=2)
try:
    with db.pool.connection() as leader:
        leader.autocommit = True
        with leader.cursor() as gate:
            gate.execute("SET statement_timeout='8s'")
            gate.execute("SELECT operations.jobs_try_schedule_leader()")
            if not gate.fetchone()[0]:
                raise RuntimeError("Scheduler leader busy")
            print(json.dumps({"scheduler_paused_for_recovery":True}),flush=True)
            try:
                with db.transaction() as cur:
                    cur.execute("SET LOCAL operations.tenant_id='1'")
                    cur.execute("SET LOCAL statement_timeout='8s'")
                    cur.execute("SELECT id FROM operations.users WHERE tenant_id=1 AND is_active AND is_superuser ORDER BY id LIMIT 1")
                    actor = cur.fetchone()[0]
                    cur.execute("SELECT id,job_key FROM operations.operator_job_runs WHERE tenant_id=1 AND status IN ('queued','running') AND NOT (job_key=ANY(%s))",(list(allowed),))
                    competitors = cur.fetchall()
                    for run, key in competitors:
                        cur.execute("SELECT operations.jobs_cancel_v1(1,%s,%s,%s)",(run,actor,"User-authorized exclusive Software recovery window."))
                        print(json.dumps({"stop":key,"outcome":cur.fetchone()[0]}),flush=True)
                deadline = time.monotonic()+175
                previous = None
                while time.monotonic()<deadline:
                    with db.transaction() as cur:
                        cur.execute("SET LOCAL operations.tenant_id='1'")
                        cur.execute("SET LOCAL statement_timeout='8s'")
                        cur.execute("SELECT operations.software_overview_inputs(1)")
                        inputs = cur.fetchone()[0]
                        cur.execute("SELECT job_key FROM operations.operator_job_runs WHERE tenant_id=1 AND status IN ('queued','running')")
                        active = {r[0] for r in cur.fetchall()}
                        cur.execute("SELECT count(*) FROM operations.software_reclassification_targets WHERE tenant_id=1 AND consumed_at IS NULL")
                        pending = cur.fetchone()[0]
                        cur.execute("SELECT count(*) FROM operations.software_overview_current WHERE tenant_id=1 AND contract_ready")
                        published = cur.fetchone()[0]
                    state = {"targets":pending,"ownership_pending":inputs.get("ownership_pending"),"owners_not_ready":[k for k,v in inputs["owners"].items() if not v.get("ready")],"jobs":sorted(active),"published":published}
                    if state != previous:
                        print(json.dumps(state),flush=True)
                        previous = state
                    if published:
                        break
                    requests = []
                    if inputs.get("ownership_pending") and not active.intersection({"computer-client-ownership","computer-client-ownership-sweep"}):
                        requests.append("computer-client-ownership")
                    if pending and not active.intersection({"software-classify","software-classify-only","software-classify-full"}):
                        requests.append("software-classify-only")
                    if not inputs["owners"].get("platform-evaluate",{}).get("ready") and "platform-evaluate" not in active:
                        requests.append("platform-evaluate")
                    if not requests and not pending and not inputs.get("ownership_pending") and not state["owners_not_ready"] and "software-overview" not in active:
                        requests.append("software-overview")
                    for key in requests:
                        run = operator_job_queue.request_system_job(key,"user-authorized-software-exclusive-recovery")
                        print(json.dumps({"requested":key,"run_id":str(run)}),flush=True)
                    time.sleep(8)
            finally:
                gate.execute("SELECT operations.jobs_release_schedule_leader()")
                print(json.dumps({"scheduler_resumed":gate.fetchone()[0]}),flush=True)
finally:
    db.pool.close()
