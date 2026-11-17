"""Approved-use-only sampled parity and one bounded Coverage candidate read.

No HTTP, application changes, query text, parameters, business row values,
credentials or exception messages in output. Copy with the two reviewed helpers.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

from plan056_coverage_candidate import candidate_sql
from plan056_coverage_components import (
    COMPUTER_AST,
    COVERAGE_AST,
    emit,
    fingerprint,
    function_from,
    initial_queries,
)


def sample_query(original):
    start = "\n                FROM operations.v_hudu_computer_inventory_observation_current hudu"
    end = "LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle"
    if original.count(start) != 1 or original.count(end) != 1:
        raise ValueError("unexpected_population_query")
    population = original[original.index(start) : original.index(end)]
    return (
        "SELECT DISTINCT hudu.observation_id"
        + population
        + " ORDER BY hudu.observation_id LIMIT 3"
    )


def read(cur, label, sql, parameters=None, *, retain=False):
    emit("validation_start", label=label)
    started = time.monotonic()
    cur.execute(sql, parameters)
    count = 0
    rows = []
    while batch := cur.fetchmany(1024):
        count += len(batch)
        if count > (4096 if retain else 100000):
            raise ValueError("result_processing_bound")
        if retain:
            rows.extend(batch)
    emit(
        "validation_read",
        label=label,
        elapsed_s=round(time.monotonic() - started, 3),
        rows=count,
    )
    return rows


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
    label, original = initial_queries(function)[1]
    if label != "hudu_inventory_lifecycle":
        emit("stopped", reason="unexpected_component_no_queries")
        return 1
    candidate = candidate_sql(original)
    ids_sql = sample_query(original)
    condition = " WHERE hudu.observation_id = ANY(%s::uuid[])"
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
        application_name="plan056_coverage_validate",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 "
        "-c search_path=operations,public",
    ) as conn:
        emit(
            "validation_scope",
            backend_pid=conn.info.backend_pid,
            role="existing_runtime",
            max_selects=4,
            sample_max_observations=3,
            statement_deadline_s=3,
        )
        phase = "transaction_setup"
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cur.execute("SET LOCAL operations.tenant_id = 1")
                phase = "sample_ids"
                selected = read(cur, phase, ids_sql, retain=True)
                identifiers = [row[0] for row in selected]
                if not identifiers:
                    raise ValueError("empty_sample_no_full_read")
                phase = "sample_original"
                before = read(
                    cur, phase, original + condition, [identifiers], retain=True
                )
                phase = "sample_candidate"
                after = read(
                    cur, phase, candidate + condition, [identifiers], retain=True
                )
                equal = Counter(before) == Counter(after)
                emit(
                    "sample_parity",
                    observations=len(identifiers),
                    original_rows=len(before),
                    candidate_rows=len(after),
                    equal_multiset=equal,
                    same_snapshot=True,
                )
                if not equal or not before:
                    raise ValueError("sample_parity_not_established_no_full_read")
                phase = "full_candidate"
                read(cur, phase, candidate)
        except Exception as error:
            emit(
                "validation_failed",
                phase=phase,
                error=type(error).__name__,
                sqlstate=getattr(error, "sqlstate", None),
                no_more_queries=True,
            )
            status = 1
    emit("validation_finished", status=status, connection_closed=True)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
