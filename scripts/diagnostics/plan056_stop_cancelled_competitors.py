"""Stop only competing children whose governed cancellation is already recorded."""
import json
import logging
import os
from pathlib import Path
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/app")
signal.alarm(20)
from ingest import db
from ingest.config import settings

allowed = {"source-record-assess", "software-queue-drain", "source-refresh", "patch-classify"}
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc/'cmdline').read_bytes().split(b'\0')
            if b'ingest.jobs_child' not in args:
                continue
            index = args.index(b'ingest.jobs_child')
            key, run = args[index+1].decode(), args[index+2].decode()
            if key not in allowed:
                continue
            descriptor = os.pidfd_open(int(proc.name))
            try:
                with db.transaction() as cur:
                    cur.execute("SET LOCAL operations.tenant_id='1'")
                    cur.execute("SET LOCAL statement_timeout='3s'")
                    cur.execute("SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs WHERE tenant_id=1 AND id=%s AND job_key=%s AND status='running' AND cancellation_requested_at IS NOT NULL)",(run,key))
                    cancelled = cur.fetchone()[0]
                if cancelled:
                    signal.pidfd_send_signal(descriptor,signal.SIGTERM)
                    print(json.dumps({'stopped_cancelled_child':key}),flush=True)
            finally:
                os.close(descriptor)
        except (FileNotFoundError,ProcessLookupError):
            pass
finally:
    db.pool.close()
