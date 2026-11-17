"""Task 4 approved-use-only sequential HTTP matrix with read-only SQL snapshots.

Copy alongside plan056_http_pilot.py and plan056_db_observe.py. No Django setup,
new accounts, business writes, SQL text, credentials or response bodies in output.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from plan056_db_observe import query
from plan056_http_pilot import emit, main


ROUTES = (
    "/admin/settings/",
    "/",
    "/orgs/all/",
    "/devices/",
    "/findings/",
    "/sources/",
    "/inventory/source-records/",
    "/software/",
    "/patching/",
    "/admin/jobs/?refresh=off",
    "/devices/?page=2",
    "/inventory/source-records/?page=2",
    "/inventory/computers/",
)
SNAPSHOT = """
SELECT jsonb_build_object(
 'database', (SELECT to_jsonb(d) FROM (
   SELECT numbackends,blks_read,blks_hit,temp_files,temp_bytes,deadlocks,
          tup_inserted,tup_updated,tup_deleted,stats_reset
   FROM pg_stat_database WHERE datname=current_database()) d),
 'recent_active_jobs', (SELECT coalesce(jsonb_agg(to_jsonb(j)), '[]') FROM (
   SELECT job_key,status,wait_category,started_at,rows_touched,
          extract(epoch FROM clock_timestamp()-requested_at) AS requested_age_s
   FROM operations.operator_job_runs
   WHERE tenant_id=1 AND requested_at >= now()-interval '24 hours'
     AND status IN ('running','queued')
   ORDER BY CASE WHEN status='running' THEN 0 ELSE 1 END, requested_at DESC
   LIMIT 20) j))
"""
STOP = Path("/tmp/plan056-task4-stop")


def measure(request, prefix):
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    emit(
        "matrix_scope",
        prefix=prefix,
        role="configured_admin",
        max_gets=2 * len(ROUTES),
        default_deadline_s=20,
        coverage_deadline_s=120,
        first_repeat="unknown_worker_and_cache",
        sql_visibility="runtime_role_limited",
    )
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config.get("PORT", "5432"),
        connect_timeout=5,
        autocommit=True,
        application_name="plan056_observe",
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000",
    ) as conn:
        index = 0
        for route in ROUTES:
            for repeat in (False, True):
                index += 1
                marker = f"{prefix}_{index}"
                if STOP.exists():
                    emit("matrix_stopped", reason="host_observer_failed")
                    return 1
                if not query(conn, f"before_{index}", SNAPSHOT):
                    return 1
                url = route + ("&" if "?" in route else "?") + "_plan056=" + marker
                page_deadline = 120 if route == "/inventory/computers/" else 20
                emit(
                    "page_start",
                    marker=marker,
                    route=route,
                    repeat=repeat,
                    deadline_s=page_deadline,
                )

                def deadline(signum, frame):
                    raise TimeoutError()

                signal.signal(signal.SIGALRM, deadline)
                signal.setitimer(signal.ITIMER_REAL, page_deadline)
                started = time.monotonic()
                succeeded = False
                try:
                    with request(url, timeout=page_deadline) as response:
                        headers_s = time.monotonic() - started
                        size = 0
                        while chunk := response.read(65536):
                            size += len(chunk)
                        succeeded = response.status == 200
                        emit(
                            "page",
                            marker=marker,
                            route=route,
                            repeat=repeat,
                            status=response.status,
                            headers_s=round(headers_s, 3),
                            elapsed_s=round(time.monotonic() - started, 3),
                            bytes=size,
                        )
                except Exception as error:
                    emit(
                        "page_incomplete",
                        marker=marker,
                        route=route,
                        repeat=repeat,
                        error=type(error).__name__,
                        elapsed_s=round(time.monotonic() - started, 3),
                        server_completion="unverified",
                    )
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                if not query(conn, f"after_{index}", SNAPSHOT):
                    return 1
                if not succeeded:
                    emit(
                        "matrix_stopped",
                        reason="page_failed_no_more_gets",
                        marker=marker,
                    )
                    return 1
    emit("matrix_complete", gets=2 * len(ROUTES))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(measure))
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
