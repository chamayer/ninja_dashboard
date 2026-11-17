"""PLAN-056 task 3: bounded, read-only observation; run only after approval.

Run by path inside the existing Operations container. No Django setup, sessions,
jobs, migrations, shell commands or customer payload reads. Settings provide
existing runtime credentials; neither credentials nor exception text is printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone


METADATA = (("current_jobs", "SELECT jsonb_build_object(\n 'status_totals',(SELECT jsonb_object_agg(status,n) FROM (SELECT status,count(*) AS n FROM operations.operator_job_runs WHERE tenant_id=1 GROUP BY status) x),\n 'active',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT job_key,status,count(*) AS runs,min(requested_at) AS oldest_requested,max(heartbeat_at) AS latest_heartbeat FROM operations.operator_job_runs WHERE tenant_id=1 AND status IN ('running','queued') GROUP BY job_key,status ORDER BY job_key,status LIMIT 100) x),\n 'completed_24h',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT job_key,count(*) AS runs,min(completed_at) AS first_completed,max(completed_at) AS last_completed,round(avg(extract(epoch FROM completed_at-started_at))::numeric,3) AS avg_duration_s,round(max(extract(epoch FROM completed_at-started_at))::numeric,3) AS max_duration_s FROM operations.operator_job_runs WHERE tenant_id=1 AND status='completed' AND completed_at>=now()-interval '24 hours' GROUP BY job_key ORDER BY job_key LIMIT 100) x),\n 'health',(SELECT jsonb_build_object('running_runs',item->'running_runs','waiting_runs',item->'waiting_runs','contained_claims',item->'contained_claims') FROM operations.jobs_admin_diagnostics_v1(1,'health',1,0) LIMIT 1))"),)

SAMPLE_SQL = """
SELECT jsonb_build_object(
 'database', (SELECT to_jsonb(d) FROM (
   SELECT numbackends,xact_commit,xact_rollback,blks_read,blks_hit,
          tup_inserted,tup_updated,tup_deleted,temp_files,temp_bytes,deadlocks,
          blk_read_time,blk_write_time,stats_reset
   FROM pg_stat_database WHERE datname=current_database()) d),
 'activity', (SELECT coalesce(jsonb_agg(to_jsonb(a)), '[]') FROM (
   SELECT CASE WHEN application_name IN ('operations','ingest','plan056_observe')
               THEN application_name ELSE 'other' END AS application,
          state,wait_event_type,wait_event,count(*) AS connections,
          max(extract(epoch FROM clock_timestamp()-query_start)) AS max_query_age_s,
          max(extract(epoch FROM clock_timestamp()-xact_start)) AS max_xact_age_s
   FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
   GROUP BY 1,2,3,4 ORDER BY count(*) DESC LIMIT 50) a),
 'blockers', (SELECT coalesce(jsonb_agg(to_jsonb(b)), '[]') FROM (
   SELECT cardinality(pg_blocking_pids(pid)) AS blockers,
          extract(epoch FROM clock_timestamp()-query_start) AS query_age_s
   FROM pg_stat_activity WHERE datname=current_database() AND state='active'
     AND pid<>pg_backend_pid() ORDER BY query_start LIMIT 50) b),
 'tables', (SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]') FROM (
   SELECT relname,n_live_tup,n_dead_tup,n_tup_ins,n_tup_upd,n_tup_del,
          vacuum_count,autovacuum_count,analyze_count,autoanalyze_count,
          last_autovacuum,last_autoanalyze
   FROM pg_stat_user_tables WHERE relname IN
    ('entity_observation_current','entity_relationship_evidence_current',
     'entity_relationship_evidence_history','software_installations_current',
     'software_installations_history','software_device_readiness',
     'device_requirement_state','findings','finding_state','condition_assessments',
     'cve_match','activities','device_session_current',
     'device_patching_scope_current','device_agent_presence_current')
   ORDER BY schemaname,relname LIMIT 20) t))
"""


def emit(section, **values):
    print(
        json.dumps(
            {
                "utc": datetime.now(timezone.utc).isoformat(),
                "section": section,
                **values,
            },
            default=str,
        ),
        flush=True,
    )


def query(conn, name, sql):
    started = time.monotonic()
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '3s'")
            cur.execute("SET LOCAL lock_timeout = '1s'")
            cur.execute("SET LOCAL idle_in_transaction_session_timeout = '5s'")
            cur.execute("SET LOCAL operations.tenant_id = '1'")
            cur.execute(sql)
            result = cur.fetchone()[0]
        emit(name, elapsed_s=round(time.monotonic() - started, 3), data=result)
        return True
    except Exception as error:
        # Never print exception messages: they may contain SQL or connection data.
        emit(
            name, error=type(error).__name__, sqlstate=getattr(error, "sqlstate", None)
        )
        return False


def main():
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import psycopg
    from django.conf import settings

    config = settings.DATABASES["default"]
    # Do not use Django setup or connection initialization hooks.
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config.get("PORT", "5432"),
        connect_timeout=5,
        application_name="plan056_observe",
        autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000",
    ) as conn:
        for name, sql in METADATA:
            if not query(conn, name, sql):
                emit("stopped", reason="metadata_incomplete_no_retry")
                return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
