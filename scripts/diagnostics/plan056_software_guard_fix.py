"""Apply only the separately approved deleted-Computer readiness correction."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/app")
signal.alarm(20)
from ingest import db
from ingest.config import settings

old = """SELECT 1 FROM operations.computer_client_ownership
             WHERE tenant_id = p_tenant AND state = 'dirty'"""
new = """SELECT 1 FROM operations.computer_client_ownership owner
              JOIN operations.devices device
                ON device.tenant_id = owner.tenant_id AND device.id = owner.device_id
               AND device.deleted_at IS NULL
             WHERE owner.tenant_id = p_tenant AND owner.state = 'dirty'"""
db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SET LOCAL lock_timeout='2s'")
        cur.execute("SELECT pg_get_functiondef('operations.software_overview_inputs(bigint)'::regprocedure)")
        sql = cur.fetchone()[0]
        if sql.count(old) != 1:
            raise RuntimeError("Readiness source mismatch")
        if sys.argv[1:] == ["--apply"]:
            cur.execute(sql.replace(old,new,1))
        cur.execute("SELECT operations.software_overview_inputs(1)->>'ownership_pending'")
        print(json.dumps({"applied":sys.argv[1:]==["--apply"],"ownership_pending":cur.fetchone()[0]}),flush=True)
finally:
    db.pool.close()
