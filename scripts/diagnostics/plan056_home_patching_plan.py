"""Approved-use-only non-ANALYZE plan for Home's Patching summary query."""

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
    "patching_reads.py": "49f78e79f41653dcaca90c37425c23ffc4f8a8e494677506c5d0e7def8379a63",
    "computer_reads.py": "e665d93514faa710051c0c7eac66fd1bd9452238f48155af44418b189a0cbc72",
    "device_status.py": "6b979009d7755876ef0a3f5ec1137a9de44a14d02929edc81e416532ad8ef5ba",
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


def reviewed_statement_count(source: str) -> bool:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "home_summary"
    )
    sql_calls = [
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
    return len(sql_calls) == 1


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
        if normalized.startswith("WITH current_computers AS ("):
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
        allowed = (
            "SET LOCAL OPERATIONS.TENANT_ID = 1",
            "SELECT TO_REGCLASS('NINJA_PATCHES.PATCH_OUTCOME_COUNTS') IS NOT NULL",
        )
        if upper.startswith(allowed) or upper.startswith(
            ("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")
        ):
            self.cursor.execute(statement, params)
            return self
        raise StopMeasurement("unexpected_statement_shape")

    def fetchone(self):
        if self.plan_row_pending:
            self.plan_row_pending = False
            return (0, 0, 0, 0, 0, 0, 0, 0, 0, None)
        return self.cursor.fetchone()


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
        source = (core / "patching_reads.py").read_text(encoding="utf-8")
        if not reviewed_statement_count(source):
            emit("source_gate_failed", module="patching_reads.py", reason="query_shape")
            return 1
    except Exception as error:
        emit("source_gate_failed", module="patching_reads.py", error=type(error).__name__)
        return 1

    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connections, transaction
        from django.utils import timezone
        from apps.core import patching_reads
        from apps.core.device_status import get_device_status_policy
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        return 1

    connection = connections["default"]
    original_cursor = connection.cursor
    status = 0
    captured_cursors = []
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cursor.execute("SET LOCAL operations.tenant_id = '1'")
                cursor.execute("SET LOCAL statement_timeout = '3000ms'")
                cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            emit("plan_started", backend_pid=backend_pid, tenant=1, analyze=False)

            try:
                policy = get_device_status_policy(1)

                def cursor_factory(*args, **kwargs):
                    wrapped = PlanCursor(original_cursor(*args, **kwargs))
                    captured_cursors.append(wrapped)
                    return wrapped

                connection.cursor = cursor_factory
                patching_reads.home_summary(now=timezone.now(), policy=policy)
            except StopMeasurement as error:
                emit("plan_stopped", reason=str(error), no_retry=True)
                raise
            except Exception as error:
                emit(
                    "plan_failed",
                    error=type(error).__name__,
                    sqlstate=sqlstate(error),
                    no_retry=True,
                )
                raise StopMeasurement from None
            finally:
                connection.cursor = original_cursor

            plan_cursor = next(
                (cursor for cursor in captured_cursors if cursor.plan is not None), None
            )
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
    except StopMeasurement:
        status = 1
    except Exception as error:
        emit("measurement_failed", error=type(error).__name__, sqlstate=sqlstate(error))
        status = 1
    finally:
        connection.cursor = original_cursor
        connection.close()
        emit("plan_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
