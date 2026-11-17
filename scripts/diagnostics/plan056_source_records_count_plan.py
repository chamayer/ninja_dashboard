"""Approved-use-only non-ANALYZE plan for Source Records default count."""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import emit, fingerprint, function_from


RECORDS_AST = "ffe8b1fd3de4e397154ddeef0573275fa9d224f1273e10b7caf960bd5302a421"
PLAN_FIELDS = (
    "Node Type", "Parent Relationship", "Join Type", "Relation Name", "Schema",
    "Alias", "Index Name", "Function Name", "CTE Name", "Scan Direction",
    "Startup Cost", "Total Cost", "Plan Rows", "Plan Width", "Parallel Aware",
)


def selected_sql(function):
    clauses = next(
        node.value for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "clauses"
                for target in node.targets)
    )
    default_clauses = ast.literal_eval(clauses)
    if default_clauses != [
        "observation.tenant_id = %s",
        "EXISTS (SELECT 1 FROM operations.source_record_subjects record_subject "
        "WHERE record_subject.tenant_id = observation.tenant_id "
        "AND record_subject.observation_id = observation.observation_id "
        "AND record_subject.subject_kind = 'record')",
    ]:
        raise ValueError("unexpected_default_population")
    where_sql = " AND ".join(default_clauses)
    calls = sorted(
        (node for node in ast.walk(function)
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
         and isinstance(node.func.value, ast.Name) and node.func.value.id == "cur"
         and node.func.attr == "execute"),
        key=lambda node: node.lineno,
    )
    matches = []
    for call in calls:
        if not call.args or not isinstance(call.args[0], ast.JoinedStr):
            continue
        parts = []
        for value in call.args[0].values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (isinstance(value, ast.FormattedValue)
                  and isinstance(value.value, ast.Name)
                  and value.value.id == "where_sql"
                  and value.conversion == -1 and value.format_spec is None):
                parts.append(where_sql)
            else:
                raise ValueError("unexpected_count_interpolation")
        sql = "".join(parts)
        if sql.lstrip().startswith(
            "SELECT COUNT(*)::int FROM operations.v_entity_observation_admin_metadata"
        ):
            matches.append((call, sql))
    if len(matches) != 1:
        raise ValueError("unexpected_count_query")
    call, sql = matches[0]
    if (len(call.args) != 2 or call.keywords
            or ast.dump(call.args[1]) != ast.dump(ast.Name(id="params", ctx=ast.Load()))
            or sql.count("%s") != 1):
        raise ValueError("unexpected_count_parameters")
    return sql


def safe_nodes(root):
    stack = [(root, None)]
    rows = []
    while stack and len(rows) < 120:
        node, parent = stack.pop()
        index = len(rows)
        rows.append({"index": index, "parent": parent,
                     **{field: node[field] for field in PLAN_FIELDS if field in node}})
        stack.extend((child, index) for child in reversed(node.get("Plans", [])))
    return rows, bool(stack)


def main():
    function = function_from(
        Path("/app/apps/core/views.py").read_text(encoding="utf-8"), "source_records"
    )
    if fingerprint(function) != RECORDS_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    sql = selected_sql(function)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    status = 0
    with psycopg.connect(
        dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"],
        host=config["HOST"], port=config.get("PORT", "5432"), connect_timeout=5,
        autocommit=True, application_name="plan056_source_records_count_plan",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit("plan_scope", backend_pid=conn.info.backend_pid,
             label="source_records_total", analyze=False)
        started = time.monotonic()
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    "EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + sql, (1,)
                )
                document = cur.fetchone()[0]
            nodes, truncated = safe_nodes(document[0]["Plan"])
            emit("estimated_plan", elapsed_s=round(time.monotonic() - started, 3),
                 nodes=nodes, truncated=truncated, actual_execution=False)
        except Exception as error:
            emit("plan_failed", error=type(error).__name__,
                 sqlstate=getattr(error, "sqlstate", None),
                 elapsed_s=round(time.monotonic() - started, 3), no_retry=True)
            status = 1
    emit("plan_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
