"""One production snapshot comparison; aggregate write is always rolled back."""

import hashlib
import json
import logging
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    expected = "b2710d0ca224d40f6e151415387d1538d3c4b5f5bd81704a0e85612c6aa1d1b4"
    if hashlib.sha256(Path("/app/apps/core/views.py").read_bytes()).hexdigest() != expected:
        raise RuntimeError("Compatibility reader source gate failed")
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    import psycopg
    from django.conf import settings
    from django.db import connection, transaction
    from psycopg import sql

    from apps.core import views
    from apps.core.software_overview import _context

    runtime = settings.DATABASES["default"]
    owner = psycopg.connect(
        dbname=runtime["NAME"],
        host=runtime["HOST"],
        port=runtime["PORT"],
        user=settings.OPERATIONS_MIGRATE_DB_USER,
        password=settings.OPERATIONS_MIGRATE_DB_PASSWORD,
        options="-c search_path=operations,public",
        connect_timeout=5,
        application_name="plan056-software-parity",
    )
    try:
        with owner.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='15s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            cursor.execute("SELECT operations.refresh_software_overview(1)")
            cursor.fetchone()
            cursor.execute("SELECT to_jsonb(summary) FROM operations.software_overview_current summary WHERE tenant_id=1")
            data = cursor.fetchone()[0]
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute(sql.SQL("SET TRANSACTION SNAPSHOT {}").format(sql.Literal(snapshot)))
                cursor.execute("SET LOCAL operations.tenant_id='1'")
                cursor.execute("SET LOCAL statement_timeout='15s'")
                cursor.execute("SET LOCAL lock_timeout='1s'")
            request = SimpleNamespace(GET={}, resolver_match=SimpleNamespace(url_name="software_page"))
            live = views._software_overview_data(request)
            prepared = _context({"state": "current", "reason": "completed", "data": data})
            mismatches = []
            checked = 0
            for key, value in prepared.items():
                if key == "overview_publication":
                    continue
                if isinstance(value, dict) and key == "workflow_state":
                    for field, count in value.items():
                        checked += 1
                        if live[key][field] != count:
                            mismatches.append(f"{key}.{field}")
                else:
                    checked += 1
                    if live[key] != value:
                        mismatches.append(key)
            print(json.dumps({"check": "same_snapshot_parity", "compared_fields": checked, "mismatched_fields": mismatches, "values_discarded": True}))
            if mismatches:
                raise RuntimeError("Compatibility comparison failed")
    finally:
        owner.rollback()
        owner.close()
        connection.close()


def deadline(signum, frame):
    raise TimeoutError("Bounded comparison deadline")


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(60)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__, "aggregate_rolled_back": True}))
        raise SystemExit(1) from None
