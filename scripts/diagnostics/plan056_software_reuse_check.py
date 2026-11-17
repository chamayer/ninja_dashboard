"""Execute only the candidate eligibility SELECT, read-only; no producer run."""
import ast
import json
import logging
from pathlib import Path
import signal
import sys
import time

logging.disable(logging.CRITICAL)
signal.alarm(20)
sys.path.insert(0,'/app')
from ingest import db
from ingest.config import settings

source=ast.parse(Path(__file__).with_name('plan056_software_reuse_candidate.py').read_text())
function=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='refresh_overview_read_model')
sql=next(node.args[0].value for node in ast.walk(function) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='execute' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and 'SELECT EXISTS' in node.args[0].value and 'software_overview_current' in node.args[0].value)
db.init(settings.postgres_dsn,min_size=1,max_size=1)
try:
    with db.transaction() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute('SELECT operations.software_overview_inputs(1)')
        checkpoint=cur.fetchone()[0]
        cur.execute("SELECT contract_ready, exposure_expires_at IS NULL OR exposure_expires_at>clock_timestamp(), input_watermarks->'owners' FROM operations.software_overview_current WHERE tenant_id=1")
        prior=cur.fetchone()
        print(json.dumps({'certified':prior[0],'prior_exposure_valid':prior[1],'changed_owner_keys':[key for key,value in checkpoint['owners'].items() if value!=prior[2].get(key)]}),flush=True)
        cur.execute("SELECT rows_touched,status,terminal_reason FROM operations.operator_job_runs WHERE tenant_id=1 AND id=%s",(checkpoint['owners']['computer-client-ownership']['run_id'],))
        print(json.dumps({'ownership_output':cur.fetchone()}),flush=True)
        started=time.monotonic()
        cur.execute(sql,(1,*(json.dumps(checkpoint),)*5,1))
        print(json.dumps({'reusable':cur.fetchone()[0],'eligibility_s':round(time.monotonic()-started,3),'writes':False}),flush=True)
finally:
    db.pool.close()
