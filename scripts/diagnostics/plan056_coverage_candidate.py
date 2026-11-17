"""Approved-use-only single candidate plan for a correlated Coverage lifecycle lookup.

Copy with the unchanged plan056_coverage_components.py helper. Output excludes
expressions, query text, row values, identifiers from business data and secrets.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from plan056_coverage_components import (
    COMPUTER_AST,
    COVERAGE_AST,
    emit,
    fingerprint,
    function_from,
    initial_queries,
)


PLAN_FIELDS = (
    "Node Type",
    "Parent Relationship",
    "Join Type",
    "Relation Name",
    "Schema",
    "Alias",
    "Index Name",
    "Function Name",
    "CTE Name",
    "Scan Direction",
    "Startup Cost",
    "Total Cost",
    "Plan Rows",
    "Plan Width",
    "Parallel Aware",
)


def safe_nodes(root):
    stack = [(root, None)]
    rows = []
    while stack and len(rows) < 120:
        node, parent = stack.pop()
        index = len(rows)
        row = {field: node[field] for field in PLAN_FIELDS if field in node}
        rows.append({"index": index, "parent": parent, **row})
        stack.extend((child, index) for child in reversed(node.get("Plans", [])))
    return rows, bool(stack)


def candidate_sql(sql):
    original = """LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
                  ON lifecycle.tenant_id = hudu.tenant_id
                 AND lifecycle.observation_id = hudu.observation_id"""
    candidate = """LEFT JOIN LATERAL (
                    SELECT lifecycle.record_lifecycle
                    FROM operations.v_device_source_record_lifecycle_current lifecycle
                    WHERE lifecycle.tenant_id = hudu.tenant_id
                      AND lifecycle.observation_id = hudu.observation_id
                    OFFSET 0
                ) lifecycle ON TRUE"""
    if sql.count(original) != 1:
        raise ValueError("unexpected_lifecycle_join_no_query")
    return sql.replace(original, candidate)


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
    label, sql = initial_queries(function)[1]
    if label != "hudu_inventory_lifecycle":
        emit("stopped", reason="unexpected_component_no_queries")
        return 1
    sql = candidate_sql(sql)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    status = 0
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config.get("PORT", "5432"),
        connect_timeout=5,
        autocommit=True,
        application_name="plan056_coverage_candidate",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit(
            "plan_scope",
            backend_pid=conn.info.backend_pid,
            label=label,
            variant="correlated_lifecycle_offset_zero",
            analyze=False,
        )
        started = time.monotonic()
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute("EXPLAIN (FORMAT JSON, VERBOSE TRUE, COSTS TRUE) " + sql)
                document = cur.fetchone()[0]
            nodes, truncated = safe_nodes(document[0]["Plan"])
            emit(
                "estimated_plan",
                elapsed_s=round(time.monotonic() - started, 3),
                nodes=nodes,
                truncated=truncated,
                actual_execution=False,
            )
        except Exception as error:
            emit(
                "plan_failed",
                error=type(error).__name__,
                sqlstate=getattr(error, "sqlstate", None),
                elapsed_s=round(time.monotonic() - started, 3),
                no_retry=True,
            )
            status = 1
    emit("plan_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
