"""Approved-use-only bulk timings for remaining Home readers and context."""

from __future__ import annotations

import hashlib
import logging
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


EXPECTED = {
    "views.py": "8701f537683df51e24b0eb7e6d15c945aacd44c3b5d5deea01ca891c7e8927c5",
    "context_processors.py": "b28231551515f1bae15d679950433dd819603895ee6bf92037a60e346b32d7b4",
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
        from apps.core import views, context_processors
        from django.core.cache import caches
        from django.core.cache.backends.locmem import LocMemCache
        if not isinstance(caches["default"], LocMemCache):
            emit("setup_failed", error="UnexpectedCacheBackend")
            return 1
        if caches["default"].get("nav_patching_open:1") is not None:
            emit("setup_failed", error="CacheNotCold")
            return 1
        logging.disable(logging.CRITICAL)
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        return 1

    status = 0
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
            emit("measurement_started", backend_pid=backend_pid, tenant=1)

            def measure(label, reader):
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
                        no_retry=True,
                    )
                    raise StopMeasurement from None
                emit(
                    "component_complete",
                    component=label,
                    elapsed_s=round(time.monotonic() - started, 3),
                    values_discarded=True,
                )
                return result

            now = timezone.now()
            request = SimpleNamespace(
                tenant_id=1, path_info="/", home_issues_open_count=0,
                resolver_match=SimpleNamespace(url_name="home"),
                user=SimpleNamespace(is_authenticated=True),
            )
            components = [
                ("sources", lambda: views._sources_home_summary(now)),
                ("jobs", lambda: views._jobs_home_summary(now)),
                ("home_context_cold", lambda: context_processors.brand(request)),
                ("home_context_warm", lambda: context_processors.brand(request)),
            ]
            for label, reader in components:
                measure(label, reader)
    except StopMeasurement:
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
