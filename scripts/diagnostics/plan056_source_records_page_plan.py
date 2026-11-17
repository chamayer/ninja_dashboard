"""Approved-use-only non-ANALYZE plan for Source Records default page rows."""

from __future__ import annotations

import ast
import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import emit, fingerprint, function_from


RECORDS_AST = "ffe8b1fd3de4e397154ddeef0573275fa9d224f1273e10b7caf960bd5302a421"
SOURCE_CLIENT_SQL = (
    "operations.computer_client_independent_evidence("
    "observation.tenant_id, observation.observation_id)"
)
PROPOSED_OTHER_SQL = (
    "EXISTS (SELECT 1 FROM operations.entity_candidates candidate"
    " WHERE candidate.tenant_id = observation.tenant_id"
    " AND candidate.source_instance_id = observation.source_instance_id"
    " AND candidate.external_id = observation.external_id"
    " AND candidate.status IN ('observed_only', 'pending')"
    " AND candidate.proposed_entity_class_id <> 'device')"
)
PLAN_FIELDS = (
    "Node Type", "Parent Relationship", "Join Type", "Relation Name", "Schema",
    "Alias", "Index Name", "Function Name", "CTE Name", "Scan Direction",
    "Startup Cost", "Total Cost", "Plan Rows", "Plan Width", "Parallel Aware",
)


def selected_sql(function, module):
    clauses = next(
        node.value for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "clauses"
                for target in node.targets)
    )
    defaults = ast.literal_eval(clauses)
    if defaults != [
        "observation.tenant_id = %s",
        "EXISTS (SELECT 1 FROM operations.source_record_subjects record_subject "
        "WHERE record_subject.tenant_id = observation.tenant_id "
        "AND record_subject.observation_id = observation.observation_id "
        "AND record_subject.subject_kind = 'record')",
    ]:
        raise ValueError("unexpected_default_population")
    where_sql = " AND ".join(defaults)

    constants = {}
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {
                "_SOURCE_RECORD_CLIENT_SQL", "_PROPOSED_OTHER_SQL"
            }:
                constants[target.id] = ast.literal_eval(node.value)
    if constants != {
        "_SOURCE_RECORD_CLIENT_SQL": SOURCE_CLIENT_SQL,
        "_PROPOSED_OTHER_SQL": PROPOSED_OTHER_SQL,
    }:
        raise ValueError("unexpected_page_sql_constants")

    assignment = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "records_sql"
                for target in node.targets)
    )
    if not isinstance(assignment.value, ast.JoinedStr):
        raise ValueError("unexpected_page_sql_expression")
    parts = []
    for value in assignment.value.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
            allowed = {
                "where_sql": where_sql,
                "_SOURCE_RECORD_CLIENT_SQL": SOURCE_CLIENT_SQL,
                "_PROPOSED_OTHER_SQL": PROPOSED_OTHER_SQL,
            }
            if (value.value.id not in allowed or value.conversion != -1
                    or value.format_spec is not None):
                raise ValueError("unexpected_page_sql_interpolation")
            parts.append(allowed[value.value.id])
        else:
            raise ValueError("unexpected_page_sql_value")
    sql_template = "".join(parts)
    if sql_template.count("{limit}") != 1:
        raise ValueError("unexpected_page_limit_marker")
    sql = sql_template.replace("{limit}", "LIMIT %s OFFSET %s")

    matches = []
    for call in ast.walk(function):
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                or not isinstance(call.func.value, ast.Name)
                or call.func.value.id != "cur" or call.func.attr != "execute"
                or not call.args or not isinstance(call.args[0], ast.Call)):
            continue
        replace_call = call.args[0]
        if (isinstance(replace_call.func, ast.Attribute)
                and isinstance(replace_call.func.value, ast.Name)
                and replace_call.func.value.id == "records_sql"
                and replace_call.func.attr == "replace"
                and len(replace_call.args) == 2
                and ast.literal_eval(replace_call.args[0]) == "{limit}"
                and ast.literal_eval(replace_call.args[1]) == "LIMIT %s OFFSET %s"):
            matches.append(call)
    expected_params = ast.List(
        elts=[
            ast.Starred(value=ast.Name(id="params", ctx=ast.Load()), ctx=ast.Load()),
            ast.Name(id="page_size", ctx=ast.Load()),
            ast.BinOp(
                left=ast.BinOp(
                    left=ast.Name(id="page_number", ctx=ast.Load()),
                    op=ast.Sub(),
                    right=ast.Constant(value=1),
                ),
                op=ast.Mult(),
                right=ast.Name(id="page_size", ctx=ast.Load()),
            ),
            ast.Name(id="tenant_id", ctx=ast.Load()),
        ],
        ctx=ast.Load(),
    )
    if (len(matches) != 1 or len(matches[0].args) != 2
            or ast.dump(matches[0].args[1]) != ast.dump(expected_params)):
        raise ValueError("unexpected_page_execution_call")
    if sql.count("%s") != 4:
        raise ValueError("unexpected_page_parameter_count")
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
    source_text = Path("/app/apps/core/views.py").read_text(encoding="utf-8")
    module = ast.parse(source_text)
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "source_records"
    )
    if fingerprint(function) != RECORDS_AST:
        emit("stopped", reason="reviewed_source_mismatch_no_queries")
        return 1
    sql = selected_sql(function, module)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    status = 0
    with psycopg.connect(
        dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"],
        host=config["HOST"], port=config.get("PORT", "5432"), connect_timeout=5,
        autocommit=True, application_name="plan056_source_records_page_plan",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit("plan_scope", backend_pid=conn.info.backend_pid,
             label="source_records_default_page", analyze=False)
        started = time.monotonic()
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    "EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + sql,
                    (1, 100, 0, 1),
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
