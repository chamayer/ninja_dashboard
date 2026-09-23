from pathlib import Path


def test_operator_jobs_use_a_durable_queue_and_separate_stall_watchdog():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    migration = Path("apps/core/migrations/0178_operator_job_queue.py").read_text(encoding="utf-8")

    assert "operations.operator_job_runs" in queue
    assert "FOR UPDATE SKIP LOCKED" in queue
    assert "status = 'stalled'" in queue
    assert "operator jobs waiting for database capacity" in queue
    assert "except PoolTimeout:" in queue
    assert 'id="operator_job_queue"' in main
    assert 'id="operator_job_queue_stale_recovery"' in main
    assert "uq_operator_job_runs_active" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration


def test_jobs_status_uses_operator_language_and_safe_controls():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/admin_job_status.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert '"queued": "Queued"' in views
    assert '"stalled": "Needs attention"' in views
    assert "def admin_job_cancel" in views
    assert "status = 'queued'" in views
    assert "Cannot safely stop" in template
    assert "Job status" in template
    assert "admin_job_status" in urls
    assert "admin_job_retry" in urls
