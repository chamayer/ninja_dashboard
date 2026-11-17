"""Approved-use-only non-ANALYZE plan for Home's governed Issues query."""

from __future__ import annotations

import ast
import hashlib
import os
import sys
import time
from pathlib import Path


EXPECTED = {
    "issue_selection.py": "181d9a86c2851481ee9568b06a3f1b85dd157012cc343e0d6f8a727a6c61696c",
    "finding_registry.py": "5e4ebaf4678b7880d97783b8abd21b4cc91eeaffda5d13f5cc16e66d54332bed",
}


def query_suffix(source: str) -> str:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "home_data"
    )
    execute_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "cursor"
        and node.func.attr == "execute"
    ]
    if len(execute_calls) != 1 or len(execute_calls[0].args) != 2:
        raise ValueError("unreviewed_home_execute_shape")
    statement = execute_calls[0].args[0]
    if (
        not isinstance(statement, ast.BinOp)
        or not isinstance(statement.op, ast.Add)
        or not isinstance(statement.left, ast.Name)
        or statement.left.id != "sql"
        or not isinstance(statement.right, ast.Constant)
        or not isinstance(statement.right.value, str)
        or not isinstance(execute_calls[0].args[1], ast.Name)
        or execute_calls[0].args[1].id != "params"
    ):
        raise ValueError("unreviewed_home_query_expression")
    return statement.right.value


def plan_nodes(root: dict) -> tuple[list[dict], bool]:
    fields = (
        "Node Type", "Parent Relationship", "Join Type", "Relation Name",
        "Schema", "Alias", "Index Name", "Function Name", "CTE Name",
        "Scan Direction", "Startup Cost", "Total Cost", "Plan Rows",
        "Plan Width", "Parallel Aware",
    )
    stack = [(root, None)]
    rows = []
    while stack and len(rows) < 120:
        node, parent = stack.pop()
        index = len(rows)
        rows.append(
            {
                "index": index,
                "parent": parent,
                **{field: node[field] for field in fields if field in node},
            }
        )
        stack.extend((child, index) for child in reversed(node.get("Plans", [])))
    return rows, bool(stack)


def main() -> int:
    core = Path("/app/apps/core")
    for name, expected in EXPECTED.items():
        try:
            actual = hashlib.sha256((core / name).read_bytes()).hexdigest()
        except OSError:
            print(f"source_gate_failed module={name} reason=unreadable", flush=True)
            return 1
        if actual != expected:
            print(f"source_gate_failed module={name} reason=hash_mismatch", flush=True)
            return 1

    try:
        suffix = query_suffix((core / "issue_selection.py").read_text(encoding="utf-8"))
    except Exception as error:
        print(f"source_gate_failed error={type(error).__name__}", flush=True)
        return 1

    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connection, transaction
        from apps.core.issue_selection import Scope, _filtered_sql, mapping_types
    except Exception as error:
        print(f"setup_failed error={type(error).__name__}", flush=True)
        return 1

    status = 0
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET LOCAL operations.tenant_id = '1'")
                cursor.execute("SET LOCAL statement_timeout = '3000ms'")
                cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            print(
                f"plan_started backend_pid={backend_pid} tenant=1 analyze=false",
                flush=True,
            )

            started = time.monotonic()
            try:
                sql, params = _filtered_sql(
                    Scope(status="open_paused"), summary=True, home_compact=True
                )
                params["mapping_types"] = list(mapping_types())
                statement = sql + suffix
            except Exception as error:
                print(
                    f"query_build_failed error={type(error).__name__} "
                    f"sqlstate={getattr(error, 'sqlstate', None)} "
                    f"elapsed_s={time.monotonic() - started:.3f} no_retry=true",
                    flush=True,
                )
                raise RuntimeError("query_build_failed") from None

            started = time.monotonic()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + statement,
                        params,
                    )
                    document = cursor.fetchone()[0]
                nodes, truncated = plan_nodes(document[0]["Plan"])
                print(
                    f"plan_complete elapsed_s={time.monotonic() - started:.3f} "
                    f"nodes={nodes!r} truncated={truncated} actual_execution=false",
                    flush=True,
                )
            except Exception as error:
                sqlstate = getattr(error, "sqlstate", None) or getattr(
                    getattr(error, "__cause__", None), "sqlstate", None
                )
                print(
                    f"plan_failed error={type(error).__name__} sqlstate={sqlstate} "
                    f"elapsed_s={time.monotonic() - started:.3f} no_retry=true",
                    flush=True,
                )
                raise RuntimeError("plan_failed") from None
    except Exception:
        status = 1
    finally:
        connection.close()
        print(f"plan_finished status={status} connection_closed=true", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
