"""Approval-gated ae45b463 Home reader diagnosis; no HTTP or data output."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


EXPECTED = {
    "views.py": "bd32ffdf15807dc68b806cf415d50cf345084eeefb76fa779c6481cd0ff2578c",
    "client_workspace.py": "ae0432a6e88073034c8803cb5026e560c35c71eeb696c2ce77690996f60f645f",
    "computer_reads.py": "e665d93514faa710051c0c7eac66fd1bd9452238f48155af44418b189a0cbc72",
    "source_record_views.py": "41625d15a9369dd3d89d64f4cbd8a3ea2f3e07e5ca713b66d261956f163c2688",
    "issue_selection.py": "8d148fd581a873848b40d3357d8c6761209a310b740d4f1fe28e6881dea9d385",
    "patching_reads.py": "49f78e79f41653dcaca90c37425c23ffc4f8a8e494677506c5d0e7def8379a63",
    "coverage_reads.py": "b66a46b48c58e6b7a24cc8cc90941c8b013cb9b079b3e46b91fa9ece0bfaa911",
    "software_review.py": "d4d24dd709764e495ccea83412ce0370358d62219cc85e936769635976af2775",
    "device_status.py": "6b979009d7755876ef0a3f5ec1137a9de44a14d02929edc81e416532ad8ef5ba",
    "finding_registry.py": "5e4ebaf4678b7880d97783b8abd21b4cc91eeaffda5d13f5cc16e66d54332bed",
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


class StopMeasurement(Exception):
    pass


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

    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connection, transaction
        from django.utils import timezone
        from apps.core import (
            client_workspace,
            computer_reads,
            coverage_reads,
            issue_selection,
            patching_reads,
            software_review,
            source_record_views,
            views,
        )
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        return 1

    status = 0
    backend_pid = None
    sql_metrics = {"calls": 0, "seconds": 0.0}

    def track(execute, sql, params, many, context):
        started = time.monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            sql_metrics["calls"] += 1
            sql_metrics["seconds"] += time.monotonic() - started

    try:
        with connection.execute_wrapper(track), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cursor.execute("SET LOCAL operations.tenant_id = '1'")
                cursor.execute("SET LOCAL statement_timeout = '10000ms'")
                cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                cursor.execute(
                    "SET LOCAL idle_in_transaction_session_timeout = '5000ms'"
                )
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            emit("measurement_started", backend_pid=backend_pid, tenant=1)

            now = timezone.now()

            def measure(label, reader):
                calls_before = sql_metrics["calls"]
                sql_before = sql_metrics["seconds"]
                started = time.monotonic()
                try:
                    result = reader()
                    if isinstance(result, dict) and result.get("available") is False:
                        raise RuntimeError("ReaderUnavailable")
                except Exception as error:
                    emit(
                        "component_failed",
                        component=label,
                        error=type(error).__name__,
                        sqlstate=sqlstate(error),
                        elapsed_s=round(time.monotonic() - started, 3),
                        sql_calls=sql_metrics["calls"] - calls_before,
                        sql_execute_s=round(sql_metrics["seconds"] - sql_before, 3),
                        no_retry=True,
                    )
                    raise StopMeasurement from None
                emit(
                    "component_complete",
                    component=label,
                    elapsed_s=round(time.monotonic() - started, 3),
                    sql_calls=sql_metrics["calls"] - calls_before,
                    sql_execute_s=round(sql_metrics["seconds"] - sql_before, 3),
                    values_discarded=True,
                )
                return result

            policy = measure("device_policy", lambda: views.get_device_status_policy(1))
            components = [
                ("clients", lambda: client_workspace.home_summary(now=now)),
                (
                    "computers",
                    lambda: computer_reads.home_summary(
                        active_device_days=policy["active_device_days"]
                    ),
                ),
                ("source_inventory", lambda: source_record_views.home_summary(now=now)),
                ("issues", lambda: issue_selection.home_data()),
                (
                    "patching",
                    lambda: patching_reads.home_summary(now=now, policy=policy),
                ),
                ("coverage", lambda: coverage_reads.home_summary()),
                ("software", lambda: software_review.home_summary()),
                ("sources", lambda: views._sources_home_summary(now)),
                ("jobs", lambda: views._jobs_home_summary(now)),
            ]
            for label, reader in components:
                measure(label, reader)
    except StopMeasurement:
        status = 1
    except Exception as error:
        emit(
            "measurement_failed",
            error=type(error).__name__,
            sqlstate=sqlstate(error),
            no_retry=True,
        )
        status = 1
    finally:
        connection.close()
        emit("measurement_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":

    def deadline(signum, frame):
        raise TimeoutError()

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(45)
    raise SystemExit(main())
