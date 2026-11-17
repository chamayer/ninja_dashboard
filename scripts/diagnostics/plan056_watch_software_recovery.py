"""Observe one authorized input retry and admit at most one overview refresh."""

import json
import logging
import signal
import sys
import time

logging.disable(logging.CRITICAL)
signal.alarm(600)
sys.path.insert(0, "/app")
from ingest import db, operator_job_queue
from ingest.config import settings

db.init(settings.postgres_dsn, min_size=1, max_size=1)
requested = False
previous = None
try:
    for attempt in range(30):
        with db.transaction() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL operations.tenant_id='1'")
            cur.execute("SET LOCAL statement_timeout='6s'")
            cur.execute("SET LOCAL lock_timeout='1s'")
            cur.execute("SELECT status, wait_category FROM operations.operator_job_runs WHERE tenant_id=1 AND id=%s", (sys.argv[1],))
            sweep = cur.fetchone()
            cur.execute("SELECT operations.software_overview_inputs(1)")
            inputs = cur.fetchone()[0]
            owners_not_ready = [key for key, value in inputs["owners"].items() if not value.get("ready")]
            cur.execute("SELECT status FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='software-overview' ORDER BY requested_at DESC LIMIT 1")
            overview = cur.fetchone()[0]
            cur.execute("SELECT operations.read_software_overview(1,NULL)")
            payload = cur.fetchone()[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND job_key='software-overview' AND status IN ('queued','running'))")
            publication_active = cur.fetchone()[0]
        state = {"sweep": sweep, "owners_not_ready": owners_not_ready,
                 "overview": overview, "state": payload.get("state"),
                 "reason": payload.get("reason"), "has_data": bool(payload.get("data"))}
        if state != previous or attempt % 3 == 0:
            print(json.dumps(state), flush=True)
        previous = state
        if payload.get("state") == "current" and payload.get("data"):
            print(json.dumps({"recovery_current_populated": True}), flush=True)
            break
        if sweep and sweep[0] in ("failed", "stalled", "cancelled"):
            raise RuntimeError("Recovery sweep did not complete")
        if (not owners_not_ready and not inputs.get("active")
                and not inputs.get("ownership_pending") and not inputs.get("classification_pending")
                and not publication_active and not requested):
            run = operator_job_queue.request_system_job("software-overview", "user-critical-software-recovery-publication")
            requested = True
            print(json.dumps({"requested_overview": str(run)}), flush=True)
        time.sleep(15)
    else:
        print(json.dumps({"recovery_pending": True}), flush=True)
finally:
    db.pool.close()
