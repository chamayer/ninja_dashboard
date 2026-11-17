"""Check whether materializing compact evidence removes repeated view work."""

import ast
from collections import Counter
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.db import connection, transaction
    from apps.core.models import ClientCandidate

    tree = ast.parse(Path("/app/apps/core/views.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_live_source_group_evidence")
    choices = [n.value for n in ast.walk(function) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip().startswith("SELECT DISTINCT si.source_id,")]
    if len(choices) != 1:
        raise ValueError("Unexpected evidence SQL")
    original = choices[0]
    candidate = """
        WITH compact_records AS MATERIALIZED (
            SELECT source_instance_id, platform_group_id, entity_key, device_id,
                   entity_type, active
              FROM operations.v_entity_observation_admin_metadata
             WHERE tenant_id = operations.current_tenant_id()
               AND entity_type <> 'org' AND active
        )
    """ + original.replace("operations.v_entity_observation_admin_metadata observation", "compact_records observation")
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='15s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            pairs = {
                (ref.get("source_id"), str(ref.get("external_id")))
                for refs in ClientCandidate.objects.filter(tenant_id=1, status=ClientCandidate.Status.OPEN).values_list("source_refs", flat=True)
                for ref in refs or [] if ref.get("source_id") and ref.get("external_id")
            }
            params = ([p[0] for p in pairs], [p[1] for p in pairs])
            results = []
            for label, sql in (("current", original), ("compact_once", candidate)):
                started = time.monotonic()
                cursor.execute(sql, params)
                results.append(Counter(cursor.fetchall()))
                print(json.dumps({"reader": label, "elapsed_s": round(time.monotonic()-started, 3)}), flush=True)
            equal = results[0] == results[1]
            print(json.dumps({"all_evidence_rows_equal": equal, "values_discarded": True}), flush=True)
            if not equal:
                raise ValueError("Evidence mismatch")
    finally:
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(40)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
