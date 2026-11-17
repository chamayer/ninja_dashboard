"""Bounded actual plans for three top slow readers; no row values or SQL output."""

import ast
import json
import logging
import os
import signal
import sys
from pathlib import Path

from plan056_source_records_page_plan import selected_sql


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.db import connection, transaction

    tree = ast.parse(Path("/app/apps/core/views.py").read_text())
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    records = selected_sql(functions["source_records"], tree)
    coverage = [
        n.value for n in ast.walk(functions["inventory_clients"])
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value.strip().startswith("SELECT device.client_id::text, evidence.source_name,")
    ]
    if len(coverage) != 1:
        raise ValueError("coverage_sql_shape")
    queries = [
        ("sources_counts", "SELECT * FROM operations.v_source_instance_record_counts WHERE tenant_id=1", []),
        ("source_records_page", records, [1, 100, 0, 1]),
        ("inventory_clients_coverage", coverage[0], ["retired"]),
    ]
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='20s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            for label, sql, params in queries:
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
                plan = cursor.fetchone()[0][0]
                nodes = []
                stack = [plan["Plan"]]
                while stack:
                    node = stack.pop()
                    nodes.append({key: node[key] for key in (
                        "Node Type", "Relation Name", "Function Name", "Actual Rows",
                        "Actual Loops", "Actual Total Time", "Shared Hit Blocks",
                        "Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks",
                    ) if key in node})
                    stack.extend(node.get("Plans", []))
                nodes.sort(key=lambda n: n.get("Actual Total Time", 0) * n.get("Actual Loops", 1), reverse=True)
                print(json.dumps({
                    "reader": label, "planning_ms": plan.get("Planning Time"),
                    "execution_ms": plan.get("Execution Time"), "jit": plan.get("JIT"),
                    "largest_inclusive_nodes": nodes[:8],
                }), flush=True)
    finally:
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(70)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
