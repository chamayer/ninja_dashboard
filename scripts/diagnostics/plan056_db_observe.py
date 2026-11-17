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


METADATA = (
    (
        "settings",
        """
SELECT jsonb_build_object(
 'settings', (SELECT jsonb_object_agg(name, setting) FROM pg_settings WHERE name IN
 ('server_version','shared_buffers','effective_cache_size','work_mem',
  'maintenance_work_mem','max_connections','random_page_cost','track_io_timing',
  'shared_preload_libraries')),
 'superuser', (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),
 'bypassrls', (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user),
 'monitor', pg_has_role(current_user, 'pg_monitor', 'MEMBER'),
 'statements_extension', EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements'))
""",
    ),
    (
        "django_migrations",
        """
SELECT coalesce(jsonb_agg(name), '[]') FROM
 (SELECT name FROM operations.django_migrations WHERE app='operations'
  ORDER BY name DESC LIMIT 8) m
""",
    ),
    (
        "ingest_migrations",
        """
SELECT coalesce(jsonb_agg(version), '[]') FROM
 (SELECT version FROM ninja_core.schema_migrations ORDER BY version DESC LIMIT 5) m
""",
    ),
    (
        "objects",
        """
SELECT jsonb_build_object(
 'batch_attribution', to_regprocedure('operations.computer_client_independent_evidence_batch(bigint,uuid[])') IS NOT NULL,
 'patch_counts', to_regclass('ninja_patches.patch_outcome_counts') IS NOT NULL,
 'active_subject_index', to_regclass('operations.idx_findings_active_subject') IS NOT NULL,
 'patch_trigger_count', (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
   JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='ninja_patches' AND t.tgname='patch_outcome_counts_maintain' AND NOT t.tgisinternal))
""",
    ),
    (
        "schedules",
        """
SELECT coalesce(jsonb_agg(jsonb_build_object('job', item->'definition_key', 'enabled', item->'enabled',
 'cadence', item->'cadence', 'next_due_at', item->'next_due_at',
 'total', total_count)), '[]')
FROM operations.jobs_admin_diagnostics_v1(1,'schedules',50,0)
""",
    ),
    (
        "runtimes",
        """
SELECT coalesce(jsonb_agg(jsonb_build_object('kind', item->'runtime_kind',
 'heartbeat_at', item->'heartbeat_at', 'stopped_at', item->'stopped_at',
 'total', total_count)), '[]')
FROM operations.jobs_admin_diagnostics_v1(1,'runtimes',50,0)
""",
    ),
    (
        "capacity",
        """
SELECT coalesce(jsonb_agg(jsonb_build_object('template', item->'resource_template', 'capacity', item->'capacity',
 'kind', item->'policy_kind', 'total', total_count)), '[]')
FROM operations.jobs_resource_policy_diagnostics_v1(1,'resource_limits',50,0)
""",
    ),
    (
        "runs",
        """
SELECT coalesce(jsonb_agg(to_jsonb(r)), '[]') FROM (
 SELECT job_key, status, requested_at, started_at, heartbeat_at, deadline_at,
        wait_category, rows_touched
 FROM operations.operator_job_runs
 WHERE tenant_id=1 AND status IN ('queued','running','stalled')
 ORDER BY requested_at LIMIT 50) r
""",
    ),
    (
        "bindings",
        """
SELECT coalesce(jsonb_agg(to_jsonb(b)), '[]') FROM (
 SELECT binding.enabled AS binding_enabled, instance.enabled AS instance_enabled,
        CASE WHEN binding.schedule ~ '^interval:[0-9]{1,6}$'
             THEN binding.schedule ELSE 'other_or_blank' END AS cadence,
        count(*) AS bindings
 FROM operations.source_bindings binding
 JOIN operations.source_instances instance ON instance.id=binding.source_instance_id
   AND instance.tenant_id=binding.tenant_id
 WHERE binding.tenant_id=1 GROUP BY 1,2,3 LIMIT 50) b
""",
    ),
)

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
        started = time.monotonic()
        for index in range(5):
            remaining = started + index * 15 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            if not query(conn, f"sample_{index}", SAMPLE_SQL):
                emit("stopped", reason="resource_sample_failed_no_retry")
                return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
