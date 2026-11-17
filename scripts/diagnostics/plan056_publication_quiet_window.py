"""Briefly hold the existing scheduler lease; always release it afterward."""
import json
import logging
import signal
import sys
import time

logging.disable(logging.CRITICAL)
signal.alarm(100)
sys.path.insert(0, '/app')
from ingest import db
from ingest.config import settings
db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.pool.connection() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout='5s'")
            cur.execute('SELECT operations.jobs_try_schedule_leader()')
            if not cur.fetchone()[0]:
                raise RuntimeError('Scheduler lease busy')
            print(json.dumps({'scheduler_quiet_window_started':True}),flush=True)
            try:
                time.sleep(85)
            finally:
                cur.execute('SELECT operations.jobs_release_schedule_leader()')
                print(json.dumps({'scheduler_lease_released':cur.fetchone()[0]}),flush=True)
finally:
    db.pool.close()
