"""Inspect only protected read state with the Operations runtime role."""
import json
import os
import sys
sys.path.insert(0,'/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
import django
django.setup()
from django.db import connection,transaction
try:
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SELECT operations.read_software_overview(1,NULL)")
        data=cur.fetchone()[0]
        if isinstance(data,str):
            data=json.loads(data)
        print(json.dumps({'state':data.get('state'),'reason':data.get('reason'),'has_data':bool(data.get('data'))}),flush=True)
finally:
    connection.close()
