"""Approved-use-only one-shot read of the Source Records default first page."""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import emit, fingerprint, function_from
from plan056_source_records_page_plan import RECORDS_AST, selected_sql


def main():
    source_text = Path("/app/apps/core/views.py").read_text(encoding="utf-8")
    function = function_from(source_text, "source_records")
    if fingerprint(function) != RECORDS_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    sql = selected_sql(function, ast.parse(source_text))
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    status = 0
    with psycopg.connect(
        dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"],
        host=config["HOST"], port=config.get("PORT", "5432"), connect_timeout=5,
        autocommit=True, application_name="plan056_source_records_page_read",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit("read_scope", backend_pid=conn.info.backend_pid,
             label="source_records_default_page", max_rows=100, statement_timeout_ms=3000)
        started = time.monotonic()
        count = 0
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(sql, (1, 100, 0, 1))
                while batch := cur.fetchmany(101):
                    count += len(batch)
                    if count > 100:
                        raise ValueError("unexpected_result_bound")
            emit("read_complete", elapsed_s=round(time.monotonic() - started, 3),
                 rows=count, values_discarded=True)
        except Exception as error:
            emit("read_failed", error=type(error).__name__,
                 sqlstate=getattr(error, "sqlstate", None),
                 elapsed_s=round(time.monotonic() - started, 3),
                 rows_discarded=True, no_retry=True)
            status = 1
    emit("read_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
