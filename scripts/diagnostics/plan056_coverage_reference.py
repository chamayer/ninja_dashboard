"""Full Coverage multiset reference using independent view reads and a bag join.

Same runtime role/snapshot/authoritative views. No HTTP, changes or business
values in output. Avoids the SQL planner's repeated broad lifecycle join.
"""

from __future__ import annotations

from collections import Counter, defaultdict
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
from plan056_coverage_deep import rows


def left_sql(original):
    join = """LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
                  ON lifecycle.tenant_id = hudu.tenant_id
                 AND lifecycle.observation_id = hudu.observation_id"""
    archive = "lifecycle.record_lifecycle = 'archived' AS is_archived"
    if original.count(join) != 1 or original.count(archive) != 1:
        raise ValueError("unexpected_reference_shape")
    result = original.replace(join, "").replace(archive, "NULL::boolean AS is_archived")
    return result.replace(
        "SELECT hudu.observation_id", "SELECT hudu.tenant_id, hudu.observation_id", 1
    )


def reference_join(left, right):
    mapping = defaultdict(list)
    for tenant, observation, lifecycle in right:
        if tenant is not None and observation is not None:
            mapping[(tenant, observation)].append(lifecycle)
    result = Counter()
    count = 0
    for tenant, *row in left:
        matched = mapping.get((tenant, row[0]), [None])
        for lifecycle in matched:
            joined = list(row)
            joined[4] = None if lifecycle is None else lifecycle == "archived"
            result[tuple(joined)] += 1
            count += 1
            if count > 100000:
                raise ValueError("reference_output_bound")
    return result, count


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
    left_query = left_sql(original)
    candidate = candidate_sql(original)
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
            application_name="plan056_coverage_reference",
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
                    role="existing_runtime",
                    statement_limit_s=5,
                    full_original_executed=False,
                )
                phase = "outer_population"
                left = rows(cur, phase, left_query)
                phase = "lifecycle_view"
                right = rows(
                    cur,
                    phase,
                    "SELECT tenant_id, observation_id, record_lifecycle "
                    "FROM operations.v_device_source_record_lifecycle_current",
                )
                phase = "reference_join"
                started = time.monotonic()
                reference, count = reference_join(left, right)
                emit(
                    "reference_join",
                    elapsed_s=round(time.monotonic() - started, 3),
                    rows=count,
                    null_keys_preserved=True,
                    multiplicity_preserved=True,
                )
                phase = "full_candidate"
                after = rows(cur, phase, candidate)
                equal = reference == Counter(after)
                emit(
                    "full_parity",
                    same_snapshot=True,
                    equal_multiset=equal,
                    reference_rows=count,
                    candidate_rows=len(after),
                    reference="independent_existing_views_bag_left_join",
                )
                if not equal or not count:
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
