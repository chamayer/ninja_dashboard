"""Approved-use-only attribution of nine Sources/Source Records SQL components.

No HTTP, Django setup, changes, query text, parameters, row values or exception
messages in output. Imports the unchanged component helper for AST/emission only.
"""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import emit, fingerprint, function_from


SOURCES_AST = "c5020a478e6efece6d45021a06128571908b49812edc1fe4b4e6a1c1b7f719e5"
RECORDS_AST = "ffe8b1fd3de4e397154ddeef0573275fa9d224f1273e10b7caf960bd5302a421"
SOURCES_LABELS = (
    "sources_health",
    "sources_record_counts",
    "sources_active_runs",
    "sources_latest_runs",
    "sources_recent_runs",
)


def calls(function):
    return sorted(
        (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cur"
            and node.func.attr == "execute"
        ),
        key=lambda node: node.lineno,
    )


def default_sql(node, where):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        result = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                result.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id == "where_sql"
                and value.conversion == -1
                and value.format_spec is None
            ):
                result.append(where)
            else:
                raise ValueError("unexpected_interpolation")
        return "".join(result)
    raise ValueError("unexpected_sql_expression")


def queries_from(sources, records):
    source_calls = calls(sources)
    if len(source_calls) != 6:
        raise ValueError("unexpected_sources_query_count")
    source_sql = [ast.literal_eval(call.args[0]) for call in source_calls[1:]]
    queries = list(zip(SOURCES_LABELS, source_sql, strict=True))
    clauses = next(
        node.value
        for node in records.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "clauses"
            for target in node.targets
        )
    )
    default_clauses = ast.literal_eval(clauses)
    if len(default_clauses) != 2:
        raise ValueError("unexpected_default_scope")
    where = " AND ".join(default_clauses)
    found = {}
    for call in calls(records):
        node = call.args[0]
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        sql = default_sql(node, where)
        stripped = sql.strip()
        if stripped.startswith(
            "SELECT COUNT(*)::int FROM operations.v_entity_observation_admin_metadata"
        ):
            label = "source_records_total"
        elif stripped.startswith("SELECT DISTINCT observation.entity_type"):
            label = "source_record_types"
        elif stripped.startswith("SELECT DISTINCT observation.source_layout"):
            label = "source_record_layouts"
        elif stripped.startswith("SELECT id, slug, display_name"):
            label = "source_record_client_choices"
        else:
            continue
        if label in found:
            raise ValueError("duplicate_selected_component")
        found[label] = sql
    for label in (
        "source_records_total",
        "source_record_types",
        "source_record_layouts",
        "source_record_client_choices",
    ):
        queries.append((label, found[label]))
    if len(found) != 4:
        raise ValueError("unexpected_record_components")
    for _label, sql in queries:
        if not sql.lstrip().startswith("SELECT ") or sql.count("%s") != 1:
            raise ValueError("unexpected_select_or_parameters")
    return queries


def main():
    source = Path("/app/apps/core/views.py").read_text(encoding="utf-8")
    sources = function_from(source, "sources_status")
    records = function_from(source, "source_records")
    if fingerprint(sources) != SOURCES_AST or fingerprint(records) != RECORDS_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    queries = queries_from(sources, records)
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
        application_name="plan056_source_reads",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit("read_probe_scope", backend_pid=conn.info.backend_pid, max_selects=9)
        for label, sql in queries:
            emit("component_start", label=label)
            started = time.monotonic()
            count = 0
            try:
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SET LOCAL operations.tenant_id = 1")
                    cur.execute(sql, (1,))
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
    emit(
        "read_probe_finished",
        completed=completed,
        status=status,
        connection_closed=True,
    )
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
