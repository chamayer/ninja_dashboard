"""One read-only default Software reader pass; timings/call sites only."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

EXPECTED = {
    "views.py": "bd32ffdf15807dc68b806cf415d50cf345084eeefb76fa779c6481cd0ff2578c",
    "software_review.py": "d4d24dd709764e495ccea83412ce0370358d62219cc85e936769635976af2775",
    "computer_reads.py": "e665d93514faa710051c0c7eac66fd1bd9452238f48155af44418b189a0cbc72",
    "finding_registry.py": "5e4ebaf4678b7880d97783b8abd21b4cc91eeaffda5d13f5cc16e66d54332bed",
    "software_display.py": "a5230dea31fc5be25a9d72582feae5cea9240520a6e1b0bb2aadb922132e8c58",
    "csv_export.py": "4b6b5f9062deeefe111d07ce7fb2c24371b5f0899e9efedfc63a60b286a80e4c",
}


def emit(section, **values):
    print(
        json.dumps(
            {
                "utc": datetime.now(timezone.utc).isoformat(),
                "section": section,
                **values,
            }
        ),
        flush=True,
    )


class StopDiagnosis(BaseException):
    pass


def deadline(signum, frame):
    raise StopDiagnosis()


def main():
    for name, expected in EXPECTED.items():
        try:
            actual = hashlib.sha256(
                (Path("/app/apps/core") / name).read_bytes()
            ).hexdigest()
        except OSError:
            emit("source_gate_failed", module=name)
            return 1
        if actual != expected:
            emit("source_gate_failed", module=name)
            return 1
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    try:
        import django

        django.setup()
        from django.db import connection, transaction
        from apps.core import views
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        return 1

    statements = []

    def track(execute, sql, params, many, context):
        frame = sys._getframe(1)
        site = {"module": "other", "function": "other", "line": 0}
        while frame is not None:
            filename = Path(frame.f_code.co_filename)
            if filename.parent == Path("/app/apps/core"):
                site = {
                    "module": filename.name,
                    "function": frame.f_code.co_name,
                    "line": frame.f_lineno,
                }
                break
            frame = frame.f_back
        del frame
        started = time.monotonic()
        try:
            result = execute(sql, params, many, context)
        except Exception as error:
            emit(
                "sql_failed",
                **site,
                error=type(error).__name__,
                sqlstate=getattr(error, "sqlstate", None),
                elapsed_s=round(time.monotonic() - started, 3),
            )
            raise StopDiagnosis() from None
        elapsed = time.monotonic() - started
        if isinstance(sql, str) and sql.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(elapsed)
            emit("sql", index=len(statements), **site, elapsed_s=round(elapsed, 3))
        return result

    status = 1
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cursor.execute("SET LOCAL operations.tenant_id = '1'")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
            request = SimpleNamespace(
                GET={}, resolver_match=SimpleNamespace(url_name="software_page")
            )
            emit("reader_started", release="ae45b463", max_statement_s=10)
            started = time.monotonic()
            with connection.execute_wrapper(track):
                result = views._software_page_data(request)
                del result
            emit(
                "reader_complete",
                elapsed_s=round(time.monotonic() - started, 3),
                sql_execute_s=round(sum(statements), 3),
                sql_calls=len(statements),
                values_discarded=True,
            )
            status = 0
    except (StopDiagnosis, Exception) as error:
        emit("stopped", error=type(error).__name__, no_retry=True)
    finally:
        connection.close()
        emit("finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(45)
    try:
        raise SystemExit(main())
    except StopDiagnosis:
        emit("stopped", reason="process_deadline")
        raise SystemExit(1) from None
