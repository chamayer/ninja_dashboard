"""Bounded actual Coverage plans and full candidate/reference multiset comparison.

Runs only reviewed SELECTs under the existing application role. No HTTP, fixes,
query text, row values, identifiers, credentials or exception messages in output.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path
import sys
import time

from plan056_coverage_candidate import candidate_sql
from plan056_coverage_components import (
    COMPUTER_AST,
    COVERAGE_AST,
    emit,
    fingerprint,
    function_from,
    initial_queries,
)


FIELDS = (
    "Node Type",
    "Parent Relationship",
    "Join Type",
    "Relation Name",
    "Schema",
    "Alias",
    "Index Name",
    "Subplan Name",
    "CTE Name",
    "Function Name",
    "Plan Rows",
    "Plan Width",
    "Startup Cost",
    "Total Cost",
    "Actual Rows",
    "Actual Loops",
    "Actual Startup Time",
    "Actual Total Time",
    "Rows Removed by Join Filter",
    "Rows Removed by Filter",
    "Shared Hit Blocks",
    "Shared Read Blocks",
    "Temp Read Blocks",
    "Temp Written Blocks",
    "Sort Method",
    "Sort Space Used",
    "Sort Space Type",
    "Heap Fetches",
    "Inner Unique",
    "Workers Planned",
    "Workers Launched",
)


def reference_sql(original):
    join = "LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle"
    if original.count(join) != 1:
        raise ValueError("unexpected_reference_join")
    return (
        "WITH lifecycle_reference AS MATERIALIZED ("
        "SELECT tenant_id, observation_id, record_lifecycle "
        "FROM operations.v_device_source_record_lifecycle_current) "
        + original.replace(join, "LEFT JOIN lifecycle_reference lifecycle")
    )


def sample_sql(original):
    start = "\n                FROM operations.v_hudu_computer_inventory_observation_current hudu"
    end = "LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle"
    if original.count(start) != 1 or original.count(end) != 1:
        raise ValueError("unexpected_population")
    return (
        "SELECT DISTINCT hudu.observation_id"
        + original[original.index(start) : original.index(end)]
        + " ORDER BY hudu.observation_id LIMIT 3"
    )


def plan(cur, label, statement, parameters=None):
    started = time.monotonic()
    cur.execute(
        "EXPLAIN (ANALYZE, BUFFERS, TIMING, SUMMARY, FORMAT JSON) " + statement,
        parameters,
    )
    result = cur.fetchone()[0][0]
    nodes = []
    stack = [(result["Plan"], None)]
    while stack and len(nodes) < 120:
        node, parent = stack.pop()
        index = len(nodes)
        nodes.append(
            {
                "index": index,
                "parent": parent,
                **{key: node[key] for key in FIELDS if key in node},
            }
        )
        stack.extend((child, index) for child in reversed(node.get("Plans", [])))
    jit = result.get("JIT", {})
    emit(
        "actual_plan",
        label=label,
        elapsed_s=round(time.monotonic() - started, 3),
        planning_ms=result.get("Planning Time"),
        execution_ms=result.get("Execution Time"),
        jit_functions=jit.get("Functions"),
        jit_timing=jit.get("Timing"),
        truncated=bool(stack),
        nodes=nodes,
    )
    if stack:
        raise ValueError("plan_output_bound")


def rows(cur, label, statement):
    started = time.monotonic()
    cur.execute(statement)
    result = []
    while batch := cur.fetchmany(1024):
        result.extend(batch)
        if len(result) > 100000:
            raise ValueError("row_processing_bound")
    emit(
        "read",
        label=label,
        elapsed_s=round(time.monotonic() - started, 3),
        rows=len(result),
    )
    return result


def metadata(cur):
    cur.execute("""
        SELECT current_setting('server_version_num'), current_setting('jit'),
               current_setting('jit_above_cost'),
               (SELECT proleakproof FROM pg_proc
                 WHERE oid='pg_catalog.uuid_eq(uuid,uuid)'::regprocedure),
               (SELECT provolatile FROM pg_proc
                 WHERE oid='operations.current_tenant_id()'::regprocedure),
               has_table_privilege('operations.entity_observation_current','SELECT')
    """)
    version, jit, jit_threshold, leakproof, volatility, base_access = cur.fetchone()
    emit(
        "metadata",
        server_version=version,
        jit=jit,
        jit_above_cost=jit_threshold,
        uuid_eq_leakproof=leakproof,
        tenant_function_volatility=volatility,
        direct_observation_select=base_access,
    )
    cur.execute("""
        SELECT c.relname,c.reloptions,pg_get_viewdef(c.oid,true)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='operations' AND c.relname IN
          ('v_hudu_computer_inventory_observation_current',
           'v_device_source_record_lifecycle_current') ORDER BY c.relname
    """)
    views = cur.fetchall()
    if len(views) != 2 or volatility not in ("s", "i"):
        raise ValueError("unexpected_view_or_tenant_contract")
    for name, options, definition in views:
        if "security_barrier=true" not in (options or []):
            raise ValueError("security_barrier_missing")
        emit(
            "view",
            name=name,
            security_barrier=True,
            definition_sha256=hashlib.sha256(definition.encode()).hexdigest(),
            uses_current_tenant="current_tenant_id()" in definition,
            uses_lateral="LATERAL" in definition,
            uses_mapping="source_record_lifecycle_mappings" in definition,
        )


def main():
    function = function_from(
        Path("/app/apps/core/views.py").read_text(), "fleet_coverage"
    )
    helper = function_from(
        Path("/app/apps/core/computer_reads.py").read_text(), "current_computer_sql"
    )
    if fingerprint(function) != COVERAGE_AST or fingerprint(helper) != COMPUTER_AST:
        raise ValueError("source_mismatch_no_queries")
    label, original = initial_queries(function)[1]
    if label != "hudu_inventory_lifecycle":
        raise ValueError("unexpected_component")
    candidate = candidate_sql(original)
    reference = reference_sql(original)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    conn = None
    phase = "connect"
    status = 0
    try:
        with psycopg.connect(
            dbname=config["NAME"],
            user=config["USER"],
            password=config["PASSWORD"],
            host=config["HOST"],
            port=config.get("PORT", "5432"),
            connect_timeout=5,
            autocommit=True,
            application_name="plan056_coverage_deep",
            options="-c default_transaction_read_only=on -c statement_timeout=5000 "
            "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
            "-c search_path=operations,public",
        ) as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cur.execute("SET LOCAL operations.tenant_id = 1")
                emit(
                    "scope",
                    backend_pid=conn.info.backend_pid,
                    statement_limit_s=5,
                    role="existing_runtime",
                    full_original_executed=False,
                )
                phase = "metadata"
                metadata(cur)
                phase = "sample_ids"
                cur.execute(sample_sql(original))
                identifiers = [row[0] for row in cur.fetchall()]
                if not identifiers:
                    raise ValueError("empty_population")
                emit("sample", observations=len(identifiers))
                for count in (1, 3):
                    phase = f"original_{count}"
                    try:
                        with conn.transaction():
                            plan(
                                cur,
                                phase,
                                original
                                + " WHERE hudu.observation_id = ANY(%s::uuid[])",
                                [identifiers[:count]],
                            )
                    except psycopg.errors.QueryCanceled:
                        emit(
                            "bounded_timeout",
                            label=phase,
                            sqlstate="57014",
                            savepoint_rolled_back=True,
                        )
                phase = "full_candidate_plan"
                plan(cur, phase, candidate)
                phase = "full_reference_plan"
                plan(cur, phase, reference)
                phase = "full_reference_read"
                before = rows(cur, phase, reference)
                phase = "full_candidate_read"
                after = rows(cur, phase, candidate)
                equal = Counter(before) == Counter(after)
                emit(
                    "full_parity",
                    same_snapshot=True,
                    equal_multiset=equal,
                    reference_rows=len(before),
                    candidate_rows=len(after),
                    reference="existing_lifecycle_view_materialized_once",
                )
                if not equal or not before:
                    raise ValueError("full_parity_failed")
    except Exception as error:
        emit(
            "diagnostic_failed",
            phase=phase,
            error=type(error).__name__,
            sqlstate=getattr(error, "sqlstate", None),
        )
        status = 1
    finally:
        emit(
            "diagnostic_finished",
            connection_closed=conn is None or conn.closed,
            status=status,
        )
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
