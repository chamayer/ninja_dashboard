"""User-authorized cancellation of identified blockers and governed recovery."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/app")
signal.alarm(45)
from ingest import db, operator_job_queue
from ingest.config import settings

db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT id FROM operations.users WHERE tenant_id=1 AND is_active AND is_superuser ORDER BY id LIMIT 1")
        actor = cur.fetchone()[0]
        for key, run in (("patch-classify", "b79dd2d2-0825-432c-9f0d-4fd03e5bfc8d"), ("software-queue-drain", "df72d137-2b72-45ad-9064-65d733ce795a")):
            cur.execute("SELECT operations.jobs_cancel_v1(1,%s,%s,%s)", (run, actor, "User authorized stopping jobs blocking Software recovery."))
            print(json.dumps({"job":key,"cancellation":cur.fetchone()[0]}),flush=True)
    with db.transaction() as cur:
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT pid,pg_cancel_backend(pid) FROM pg_stat_activity WHERE datname=current_database() AND pid IN (515653,515768) AND backend_type='client backend' AND state='active' AND (query ILIKE '%%operations.acquire_tenant_guard%%' OR query ILIKE '%%operations.v_device_source_link%%')")
        print(json.dumps({"blocked_work_cancelled":cur.fetchall()}),flush=True)
    for key in ("computer-client-ownership", "software-classify-only"):
        run = operator_job_queue.request_system_job(key, "user-approved-software-recovery")
        print(json.dumps({"requested":key,"run_id":str(run)}),flush=True)
finally:
    db.pool.close()
