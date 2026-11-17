"""Read only Software publication status; discard all summary values."""
import json
import os
import signal
import sys

signal.alarm(15)
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
import django
django.setup()
from django.db import connection, transaction

try:
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute("SELECT operations.read_software_overview(1, NULL)")
        payload = cur.fetchone()[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        print(json.dumps({"state": payload.get("state"), "reason": payload.get("reason")}))
finally:
    connection.close()
