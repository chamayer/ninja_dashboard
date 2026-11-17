"""One read-only existing/candidate Issues count equality/timing check."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
logging.disable(logging.CRITICAL)
sys.path.insert(0,'/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
signal.alarm(25)
import django
django.setup()
from django.db import connection,transaction
from apps.core import issue_selection
spec=importlib.util.spec_from_file_location('apps.core._plan056_issue_count',Path(__file__).with_name('plan056_issue_count_candidate.py'))
candidate=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=candidate
spec.loader.exec_module(candidate)
try:
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        result=[]
        for name,reader in (('current',issue_selection),('candidate',candidate)):
            started=time.monotonic()
            result.append(reader.count(reader.Scope(status='open')))
            print(json.dumps({'reader':name,'elapsed_s':round(time.monotonic()-started,3)}),flush=True)
        print(json.dumps({'count_equal':result[0]==result[1],'values_discarded':True}),flush=True)
        if result[0]!=result[1]:
            raise RuntimeError('Count mismatch')
finally:
    connection.close()
