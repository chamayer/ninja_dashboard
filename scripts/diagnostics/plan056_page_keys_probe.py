"""Compare the exact Source Records result with key-first page enrichment."""

import ast
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from plan056_source_records_page_plan import SOURCE_CLIENT_SQL, selected_sql


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.db import connection, transaction

    tree = ast.parse(Path("/app/apps/core/views.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "source_records")
    original = selected_sql(function, tree)
    prefix = "WITH page AS MATERIALIZED (\n                SELECT observation.*"
    boundary = "),\n            group_mapping AS MATERIALIZED ("
    if original.count(prefix) != 1 or original.count(boundary) != 1:
        raise ValueError("Unexpected page definition")
    candidate = original.replace(prefix, "WITH page_keys AS MATERIALIZED (\n                SELECT observation.tenant_id, observation.observation_id", 1)
    candidate = candidate.replace(boundary, """),
            page AS MATERIALIZED (
                SELECT observation.*
                  FROM operations.v_entity_observation_admin_metadata observation
                 WHERE observation.tenant_id = operations.current_tenant_id()
                   AND observation.observation_id = ANY(ARRAY(
                       SELECT observation_id FROM page_keys))
            ),
            page_clients AS MATERIALIZED (
                SELECT * FROM operations.computer_client_independent_evidence_batch(
                    1, ARRAY(SELECT observation_id FROM page))
            ),
            group_mapping AS MATERIALIZED (""", 1)
    if candidate.count(SOURCE_CLIENT_SQL) != 2:
        raise ValueError("Unexpected attribution uses")
    candidate = candidate.replace(SOURCE_CLIENT_SQL, "page_client.client_id").replace(
        "FROM page observation", "FROM page observation LEFT JOIN page_clients page_client ON page_client.observation_id = observation.observation_id", 1
    )
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='20s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            results = []
            for label, sql in (("current", original), ("bounded_projection_and_attribution", candidate)):
                started = time.monotonic()
                cursor.execute(sql, [1, 100, 0, 1])
                results.append(cursor.fetchall())
                print(json.dumps({"reader": label, "elapsed_s": round(time.monotonic()-started, 3)}), flush=True)
            equal = results[0] == results[1]
            print(json.dumps({"all_columns_and_order_equal": equal, "values_discarded": True}), flush=True)
            if not equal:
                raise ValueError("Result mismatch")
    finally:
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(55)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
