"""Approved-use-only Coverage initial-query diagnosis; no HTTP or data output.

Uses exact reviewed deployed source ASTs and the existing runtime role. Reads
each initial HTML-path SELECT once, stopping on the first failure. Does not
execute source code from the parsed files, initialize Django, or change settings
outside this process. Query text, parameters and result values are never emitted.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


COVERAGE_AST = "ad010144ba7667bf7fa48ec46ee078336026ad4b1bf58609e87d667761227521"
COMPUTER_AST = "24c4806d7d14400142120060a625762f05958bd35037afcad874619e6ec54c25"
LABELS = (
    "stored_requirements",
    "hudu_inventory_lifecycle",
    "computer_inventory",
    "client_roster",
    "source_presence",
    "compact_source_observations",
    "agent_platforms",
    "source_record_counts",
)


def emit(section, **data):
    print(
        json.dumps(
            {"utc": datetime.now(timezone.utc).isoformat(), "section": section, **data}
        ),
        flush=True,
    )


def function_from(source, name):
    tree = ast.parse(source)
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def fingerprint(node):
    return hashlib.sha256(
        ast.dump(node, include_attributes=False).encode("utf-8")
    ).hexdigest()


def sql_from(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and value.conversion == -1
                and value.format_spec is None
                and ast.dump(value.value)
                == ast.dump(
                    ast.Call(
                        func=ast.Name(id="current_computer_sql", ctx=ast.Load()),
                        args=[ast.Constant(value="device")],
                        keywords=[],
                    )
                )
            ):
                parts.append("device.lifecycle_status <> 'retired'")
            else:
                raise ValueError("unreviewed_interpolation")
        return "".join(parts)
    raise ValueError("unreviewed_sql_expression")


def initial_queries(function):
    initial = next(node for node in function.body if isinstance(node, ast.With))
    compact = next(
        node
        for node in ast.walk(initial)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "compact_source_observations"
    )
    excluded = {id(node) for item in compact.orelse for node in ast.walk(item)}
    calls = sorted(
        (
            node
            for node in ast.walk(initial)
            if id(node) not in excluded
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cur"
            and node.func.attr == "execute"
        ),
        key=lambda node: node.lineno,
    )
    queries = []
    for call in calls:
        if len(call.args) != 1 or call.keywords:
            raise ValueError("unexpected_query_arguments")
        sql = sql_from(call.args[0])
        if sql.strip() == "SET LOCAL operations.tenant_id = 1":
            continue
        if not sql.lstrip().startswith(("SELECT ", "WITH ")):
            raise ValueError("unexpected_statement")
        queries.append(sql)
    if len(queries) != len(LABELS):
        raise ValueError("unexpected_query_count")
    return tuple(zip(LABELS, queries, strict=True))


def main():
    function = function_from(
        Path("/app/apps/core/views.py").read_text(encoding="utf-8"), "fleet_coverage"
    )
    helper = function_from(
        Path("/app/apps/core/computer_reads.py").read_text(encoding="utf-8"),
        "current_computer_sql",
    )
    if fingerprint(function) != COVERAGE_AST or fingerprint(helper) != COMPUTER_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    queries = initial_queries(function)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    completed = 0
    status = 0
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config.get("PORT", "5432"),
        connect_timeout=5,
        autocommit=True,
        application_name="plan056_coverage_probe",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit(
            "probe_scope",
            backend_pid=conn.info.backend_pid,
            role="existing_runtime",
            max_queries=8,
            statement_deadline_s=3,
            lock_deadline_s=1,
            http_requests=0,
        )
        for label, sql in queries:
            emit("component_start", label=label)
            started = time.monotonic()
            count = 0
            try:
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SET LOCAL operations.tenant_id = 1")
                    cur.execute(sql)
                    while batch := cur.fetchmany(1024):
                        count += len(batch)
                        if count > 100000:
                            raise ValueError("result_processing_bound")
                emit(
                    "component_complete",
                    label=label,
                    elapsed_s=round(time.monotonic() - started, 3),
                    rows=count,
                )
                completed += 1
            except Exception as error:
                emit(
                    "component_failed",
                    label=label,
                    elapsed_s=round(time.monotonic() - started, 3),
                    error=type(error).__name__,
                    sqlstate=getattr(error, "sqlstate", None),
                    no_more_queries=True,
                )
                status = 1
                break
    emit("probe_finished", completed=completed, status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
