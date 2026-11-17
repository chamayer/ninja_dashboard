"""Approved-use-only non-ANALYZE plan for Sources per-type record counts."""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import emit, fingerprint, function_from


SOURCES_AST = "c5020a478e6efece6d45021a06128571908b49812edc1fe4b4e6a1c1b7f719e5"
PLAN_FIELDS = (
    "Node Type", "Parent Relationship", "Join Type", "Relation Name", "Schema",
    "Alias", "Index Name", "Function Name", "CTE Name", "Scan Direction",
    "Startup Cost", "Total Cost", "Plan Rows", "Plan Width", "Parallel Aware",
)


def selected_sql(function):
    calls = sorted(
        (node for node in ast.walk(function)
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
         and isinstance(node.func.value, ast.Name) and node.func.value.id == "cur"
         and node.func.attr == "execute"),
        key=lambda node: node.lineno,
    )
    selects = [node for node in calls if node.args and isinstance(node.args[0], ast.Constant)
               and isinstance(node.args[0].value, str)
               and "FROM operations.v_source_instance_record_counts" in node.args[0].value]
    if (
        len(selects) != 1
        or len(selects[0].args) != 2
        or selects[0].keywords
        or ast.dump(selects[0].args[1])
        != ast.dump(
            ast.Tuple(
                elts=[ast.Name(id="tenant_id", ctx=ast.Load())],
                ctx=ast.Load(),
            )
        )
    ):
        raise ValueError("unexpected_record_count_query")
    sql = ast.literal_eval(selects[0].args[0])
    if not sql.lstrip().startswith("SELECT ") or "%s" not in sql:
        raise ValueError("unexpected_query_shape")
    return sql


def safe_nodes(root):
    stack = [(root, None)]
    rows = []
    while stack and len(rows) < 120:
        node, parent = stack.pop()
        index = len(rows)
        rows.append({"index": index, "parent": parent,
                     **{field: node[field] for field in PLAN_FIELDS if field in node}})
        stack.extend((child, index) for child in reversed(node.get("Plans", [])))
    return rows, bool(stack)


def main():
    function = function_from(Path("/app/apps/core/views.py").read_text(encoding="utf-8"), "sources_status")
    if fingerprint(function) != SOURCES_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    sql = selected_sql(function)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    status = 0
    with psycopg.connect(
        dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"],
        host=config["HOST"], port=config.get("PORT", "5432"), connect_timeout=5,
        autocommit=True, application_name="plan056_sources_counts_plan",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit("plan_scope", backend_pid=conn.info.backend_pid,
             label="sources_record_counts", analyze=False)
        started = time.monotonic()
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute("EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + sql, (1,))
                document = cur.fetchone()[0]
            nodes, truncated = safe_nodes(document[0]["Plan"])
            emit("estimated_plan", elapsed_s=round(time.monotonic() - started, 3),
                 nodes=nodes, truncated=truncated, actual_execution=False)
        except Exception as error:
            emit("plan_failed", error=type(error).__name__,
                 sqlstate=getattr(error, "sqlstate", None),
                 elapsed_s=round(time.monotonic() - started, 3), no_retry=True)
            status = 1
    emit("plan_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
