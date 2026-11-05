"""Contract checks for the Jobs active-scope claim guard."""

from pathlib import Path


def test_both_claim_paths_leave_active_scope_successors_queued():
    sql = Path("apps/core/migrations/0405_jobs_claim_successor_guard.py").read_text(
        encoding="utf-8"
    )

    assert sql.count("AND NOT EXISTS (") == 2
    assert sql.count("active.job_key = run.job_key") == 2
    assert sql.count("active.scope_identity = run.scope_identity") == 2
    assert sql.count("active.status = 'running'") == 2
    assert sql.count("active.wait_category IS DISTINCT FROM 'workflow'") == 2
    assert "operations.jobs_claim_next_v6(p_tenant_id, p_worker_incarnation)" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v6" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v7" in sql
