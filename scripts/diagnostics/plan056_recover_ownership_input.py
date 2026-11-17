"""User-authorized Software recovery: re-admit only its failed sweep input."""

import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
signal.alarm(25)
sys.path.insert(0, "/app")
from ingest import db, operator_job_queue
from ingest.config import settings

db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT operations.software_overview_inputs(1)")
        inputs = cur.fetchone()[0]
        failed = [key for key, value in inputs["owners"].items() if not value.get("ready")]
        if failed != ["computer-client-ownership-sweep"]:
            raise RuntimeError("Recovery input precondition changed")
        cur.execute("""SELECT status, terminal_reason FROM operations.operator_job_runs
            WHERE tenant_id=1 AND job_key='computer-client-ownership-sweep'
            AND started_at IS NOT NULL ORDER BY requested_at DESC LIMIT 1""")
        if cur.fetchone() != ("stalled", "worker_interrupted"):
            raise RuntimeError("Recovery prior-run precondition changed")
        cur.execute("""SELECT id FROM operations.operator_job_runs WHERE tenant_id=1
            AND job_key='computer-client-ownership-sweep' AND status IN ('queued','running')
            ORDER BY requested_at DESC LIMIT 1""")
        active = cur.fetchone()
    if active:
        print(json.dumps({"existing_sweep": str(active[0])}), flush=True)
    else:
        run = operator_job_queue.request_system_job(
            "computer-client-ownership-sweep", "user-critical-software-input-recovery"
        )
        print(json.dumps({"requested_sweep": str(run)}), flush=True)
finally:
    db.pool.close()
