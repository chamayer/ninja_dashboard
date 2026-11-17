"""Approved-use-only non-ANALYZE plan for Home's installed-title summary."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


EXPECTED = {
    "software_review.py": "d4d24dd709764e495ccea83412ce0370358d62219cc85e936769635976af2775",
    "computer_reads.py": "e665d93514faa710051c0c7eac66fd1bd9452238f48155af44418b189a0cbc72",
}


def emit(section: str, **data: object) -> None:
    print(
        json.dumps(
            {"utc": datetime.now(timezone.utc).isoformat(), "section": section, **data}
        ),
        flush=True,
    )


def sqlstate(error: Exception) -> str | None:
    return getattr(error, "sqlstate", None) or getattr(
        getattr(error, "__cause__", None), "sqlstate", None
    )


def reviewed_home_query(source: str) -> bool:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "home_summary"
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "cursor"
        and node.func.attr == "execute"
        and node.args
        and isinstance(node.args[0], ast.JoinedStr)
    ]
    if len(calls) != 1:
        return False
    sql = calls[0].args[0]
    literal = next(
        (
            part.value
            for part in sql.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ),
        "",
    )
    interpolations = [part for part in sql.values if isinstance(part, ast.FormattedValue)]
    if len(interpolations) != 5:
        return False
    normalized_literal = " ".join(literal.split()).upper()
    return (
        normalized_literal.startswith("WITH TITLE_PUBLISHERS AS (")
        and ast.dump(interpolations[0].value, include_attributes=False)
        == "Call(func=Name(id='current_computer_sql', ctx=Load()), args=[Constant(value='d')], keywords=[])"
        and ast.dump(interpolations[1].value, include_attributes=False)
        == "Name(id='TITLE_STATUS_CTES', ctx=Load())"
        and ast.dump(interpolations[2].value, include_attributes=False)
        == "Call(func=Name(id='current_computer_sql', ctx=Load()), args=[Constant(value='device')], keywords=[])"
        and ast.dump(interpolations[3].value, include_attributes=False)
        == "Name(id='TITLE_STATUS', ctx=Load())"
        and ast.dump(interpolations[4].value, include_attributes=False)
        == "Name(id='TITLE_STATUS_JOINS', ctx=Load())"
    )


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


class StopMeasurement(Exception):
    pass


class PlanCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.plan = None
        self.plan_elapsed = None
        self.plan_row_pending = False

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.cursor.__exit__(exc_type, exc, traceback)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, statement, params=None):
        normalized = statement.lstrip()
        prefix = (
            "WITH title_publishers AS ("
        )
        if normalized.startswith(prefix):
            if self.plan is not None:
                raise StopMeasurement("duplicate_main_query")
            started = time.monotonic()
            self.cursor.execute(
                "EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + statement,
                params,
            )
            self.plan = self.cursor.fetchone()[0]
            self.plan_elapsed = time.monotonic() - started
            self.plan_row_pending = True
            return self

        upper = normalized.upper()
        if upper.startswith("SET LOCAL OPERATIONS.TENANT_ID = 1") or upper.startswith(
            ("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")
        ):
            self.cursor.execute(statement, params)
            return self
        raise StopMeasurement("unexpected_statement_shape")

    def fetchone(self):
        if self.plan_row_pending:
            self.plan_row_pending = False
            return (0,)
        return self.cursor.fetchone()

    def fetchall(self):
        if self.plan_row_pending:
            self.plan_row_pending = False
            return []
        return self.cursor.fetchall()


def main() -> int:
    core = Path("/app/apps/core")
    for name, expected in EXPECTED.items():
        try:
            actual = hashlib.sha256((core / name).read_bytes()).hexdigest()
        except OSError:
            emit("source_gate_failed", module=name, reason="unreadable")
            return 1
        if actual != expected:
            emit("source_gate_failed", module=name, reason="hash_mismatch")
            return 1
    try:
        source = (core / "software_review.py").read_text(encoding="utf-8")
        if not reviewed_home_query(source):
            emit("source_gate_failed", module="software_review.py", reason="query_shape")
            return 1
    except Exception as error:
        emit("source_gate_failed", module="software_review.py", error=type(error).__name__)
        return 1

    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connections, transaction
        from apps.core import software_review
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        return 1

    connection = connections["default"]
    original_cursor = connection.cursor
    captured = []
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
            emit("plan_started", backend_pid=backend_pid, tenant=1, analyze=False)

            def cursor_factory(*args, **kwargs):
                wrapped = PlanCursor(original_cursor(*args, **kwargs))
                captured.append(wrapped)
                return wrapped

            try:
                connection.cursor = cursor_factory
                software_review.home_summary()
            finally:
                connection.cursor = original_cursor

            plan_cursor = next((item for item in captured if item.plan is not None), None)
            if plan_cursor is None:
                emit("plan_failed", error="MissingPlan", no_retry=True)
                raise StopMeasurement
            nodes, truncated = plan_nodes(plan_cursor.plan[0]["Plan"])
            emit(
                "plan_complete",
                elapsed_s=round(plan_cursor.plan_elapsed, 3),
                nodes=nodes,
                truncated=truncated,
                actual_execution=False,
            )
    except StopMeasurement as error:
        if str(error):
            emit("plan_stopped", reason=str(error), no_retry=True)
        status = 1
    except Exception as error:
        emit(
            "plan_failed",
            error=type(error).__name__,
            sqlstate=sqlstate(error),
            no_retry=True,
        )
        status = 1
    finally:
        connection.cursor = original_cursor
        connection.close()
        emit("plan_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
