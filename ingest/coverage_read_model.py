"""Jobs-owned Coverage publication; never invoked by an interactive GET."""

from ingest import db
from ingest.config import settings
from ingest.device_status_settings import thresholds


def refresh() -> int:
    with db.transaction() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute("SET LOCAL lock_timeout = '2s'")
        cursor.execute(
            "SELECT config FROM operations.evaluator_config "
            "WHERE tenant_id = 1 AND evaluator_name = 'device_status'"
        )
        row = cursor.fetchone()
        days = min(365, thresholds(row[0] if row else {})[0])
        cursor.execute("SELECT operations.refresh_coverage_read(%s, %s)", (1, days))
        return cursor.fetchone()[0]


def admit_due() -> int:
    """Admit refreshes ahead of expiry without relaxing reader freshness."""
    from ingest.operator_job_queue import request_system_job

    if not settings.SCHEDULED_JOBS_ENABLED:
        return 0

    with db.transaction() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
        cursor.execute(
            "SELECT to_regclass('operations.coverage_read_publication') IS NOT NULL"
        )
        if not cursor.fetchone()[0]:
            return 0
        cursor.execute(
            "SELECT NOT EXISTS (SELECT 1 FROM operations.coverage_read_publication p "
            "JOIN operations.coverage_read_revision r USING (tenant_id) "
            "WHERE p.tenant_id = 1 AND p.revision = r.revision "
            "AND p.expires_at > statement_timestamp() + interval '25 seconds') "
            "AND NOT EXISTS (SELECT 1 FROM operations.operator_job_runs "
            "WHERE tenant_id = 1 AND job_key = 'coverage-read-model' "
            "AND status IN ('queued', 'running'))"
        )
        due = cursor.fetchone()[0]
    if due:
        request_system_job("coverage-read-model", "coverage-read-model-due")
        return 1
    return 0
