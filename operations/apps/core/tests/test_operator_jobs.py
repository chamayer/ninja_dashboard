from pathlib import Path


def test_operator_jobs_use_a_durable_queue_and_separate_stall_watchdog():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    migration = Path("apps/core/migrations/0178_operator_job_queue.py").read_text(encoding="utf-8")
    progress_migration = Path("apps/core/migrations/0179_add_operator_job_progress.py").read_text(encoding="utf-8")
    workflow_migration = Path("apps/core/migrations/0180_operator_job_workflow_controls.py").read_text(encoding="utf-8")
    software_lane_migration = Path("apps/core/migrations/0182_software_job_lane_and_operations_controls.py").read_text(encoding="utf-8")

    assert "operations.operator_job_runs" in queue
    assert "FOR UPDATE SKIP LOCKED" in queue
    assert "status = 'stalled'" in queue
    assert "class JobProgress" in queue
    assert "stage_updated_at" in queue
    assert "_software_classify_with_intel" in queue
    assert "recover_interrupted" in queue
    assert "WORKER_LANES" in queue
    assert "operator jobs waiting for database capacity" in queue
    assert "except PoolTimeout:" in queue
    assert 'id=f"operator_job_queue_{lane}"' in main
    assert 'id="operator_job_queue_stale_recovery"' in main
    assert "def enqueue_automatic" in queue
    assert 'args=["patches"]' in main
    assert 'args=["platform-evaluate"]' in main
    assert 'args=["intel-nvd"]' in main
    assert "uq_operator_job_runs_active" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "stage_updated_at" in progress_migration
    assert "operator_job_events" in workflow_migration
    assert "heartbeat_at" in workflow_migration
    assert '"software-classify-full"' in queue
    assert "incremental=True" in queue
    assert "_SOFTWARE_CLASSIFIER_JOBS" in queue
    assert "job_key <> ALL" in queue
    assert "_admit_software_classifier" in queue
    assert '"software"' in queue
    assert "software-classify-full" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "_queue_software_rebuild_after_commit" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT, UPDATE ON operations.operator_job_runs TO operations_app" in software_lane_migration
    assert "Superseded by a broader Software classifier run" in software_lane_migration


def test_jobs_status_uses_operator_language_and_safe_controls():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/admin_job_status.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert '"queued": "Queued"' in views
    assert '"stalled": "Needs attention"' in views
    assert "def admin_job_cancel" in views
    assert "status = 'queued'" in views
    assert "Cannot safely stop" in template
    assert "Job activity" in template
    assert "Queue position" in template
    assert "Current work" in template
    assert "Updated" in template
    assert "Worker active" in template
    assert "Not started" in template
    assert "Waiting for work already running in this lane" in views
    assert "Recent system activity" in template
    assert '"origin": "Automatic"' in views
    assert "Show error details" in template
    assert "admin_job_history_retry" in template
    assert "_HISTORY_RETRYABLE_KINDS" in views
    assert "admin_job_history_retry" in urls
    assert "admin_job_status" in urls
    assert "admin_job_retry" in urls
