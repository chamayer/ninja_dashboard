"""Approved-use-only timings for Home Coverage, Software and Sources readers."""

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
    "coverage_reads.py": "b66a46b48c58e6b7a24cc8cc90941c8b013cb9b079b3e46b91fa9ece0bfaa911",
    "computer_reads.py": "e665d93514faa710051c0c7eac66fd1bd9452238f48155af44418b189a0cbc72",
    "software_review.py": "d4d24dd709764e495ccea83412ce0370358d62219cc85e936769635976af2775",
    "views.py": "8701f537683df51e24b0eb7e6d15c945aacd44c3b5d5deea01ca891c7e8927c5",
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


def has_one_home_query(source: str, name: str) -> bool:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
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
    return len(calls) == 1


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
        coverage_source = (core / "coverage_reads.py").read_text(encoding="utf-8")
        if not has_one_home_query(coverage_source, "home_summary"):
            emit("source_gate_failed", module="coverage_reads.py", reason="query_shape")
            return 1
    except Exception as error:
        emit("source_gate_failed", module="coverage_reads.py", error=type(error).__name__)
        return 1

    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connection, transaction
        from django.utils import timezone
        from apps.core import coverage_reads, software_review, views
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
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
            emit("measurement_started", backend_pid=backend_pid, tenant=1)

            def measure(component: str, reader) -> None:
                started = time.monotonic()
                try:
                    reader()
                except Exception as error:
                    emit(
                        "component_failed",
                        component=component,
                        error=type(error).__name__,
                        sqlstate=sqlstate(error),
                        elapsed_s=round(time.monotonic() - started, 3),
                        no_retry=True,
                    )
                    raise RuntimeError("measurement_stopped") from None
                emit(
                    "component_complete",
                    component=component,
                    elapsed_s=round(time.monotonic() - started, 3),
                    values_discarded=True,
                )

            now = timezone.now()
            measure("coverage", coverage_reads.home_summary)
            measure("software", software_review.home_summary)
            measure("sources", lambda: views._sources_home_summary(now))
    except RuntimeError as error:
        if str(error) == "measurement_stopped":
            status = 1
        else:
            emit("measurement_failed", error=type(error).__name__)
            status = 1
    except Exception as error:
        emit("measurement_failed", error=type(error).__name__, sqlstate=sqlstate(error))
        status = 1
    finally:
        connection.close()
        emit("measurement_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
