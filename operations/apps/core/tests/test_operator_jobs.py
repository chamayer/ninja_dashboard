from pathlib import Path


def test_operator_jobs_use_a_durable_queue_and_separate_stall_watchdog():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    migration = Path("apps/core/migrations/0178_operator_job_queue.py").read_text(encoding="utf-8")
    progress_migration = Path("apps/core/migrations/0179_add_operator_job_progress.py").read_text(encoding="utf-8")
    workflow_migration = Path("apps/core/migrations/0180_operator_job_workflow_controls.py").read_text(encoding="utf-8")
    software_lane_migration = Path("apps/core/migrations/0182_software_job_lane_and_operations_controls.py").read_text(encoding="utf-8")

    assert "operations.jobs_claim_next_v3" in queue
    assert "operations.jobs_finish_v1" in queue
    assert "operations.jobs_record_v1_progress" in queue
    assert "class V1JobProgress" in queue
    assert "_software_classify_with_intel" in queue
    assert "WORKER_LANES" in queue
    assert "except PoolTimeout:" in queue
    assert "contract_version = 0" not in queue
    assert "def enqueue_automatic" not in queue
    assert 'id="jobs_durable_schedule_producer"' in main
    assert "operator_job_queue.enqueue_automatic" not in main
    assert "uq_operator_job_runs_active" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "stage_updated_at" in progress_migration
    assert "operator_job_events" in workflow_migration
    assert "heartbeat_at" in workflow_migration
    assert '"software-classify-full"' in queue
    assert "incremental=True" in queue
    assert '"software"' in queue
    assert "software-classify-full" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "_queue_software_rebuild_after_commit" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT, UPDATE ON operations.operator_job_runs TO operations_app" in software_lane_migration
    assert "Superseded by a broader Software classifier run" in software_lane_migration


def test_jobs_status_uses_operator_language_and_safe_controls():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/admin_job_status.html").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert '"queued": "Queued"' in views
    assert '"stalled": "Needs attention"' in views
    assert "def admin_job_cancel" in views
    assert "jobs_cancel_v1" in views
    assert "Request cancellation" in template
    assert "Cancellation pending" in template
    assert "Job activity" in template
    assert "Queue position" in template
    assert "Current work" in template
    assert "Updated" in template
    assert "Worker active" in template
    assert "Not started" in template
    assert "Waiting for work already running in this lane" in views
    assert "Recent system activity" in template
    assert '"automatic": "Automatic"' in views
    assert '"dependency": "Dependency"' in views
    assert "Safety deadline" in template
    assert "Show error details" in template
    assert "admin_job_history_retry" in template
    assert "_HISTORY_RETRYABLE_KINDS" in views
    assert "admin_job_history_retry" in urls
    assert "admin_job_status" in urls
    assert "admin_job_retry" in urls
    assert "queued_job_status" in views
    assert "operator_job_runs" in views
    assert "capability_state" in views
    assert "scheduled_definition_keys" in views
    assert "FROM operations.job_schedules" in views
    assert "disabled_reason" in views
    assert "The durable Jobs queue is the history authority" in views
    assert "No recorded run yet" in jobs_template
    assert "No run available" in jobs_template
    assert "next due" in jobs_template
    assert "last_schedule_outcome" in jobs_template
    assert "job_domain_attempts" in views
    assert "operations.job_dependencies" in views
    assert "Technical details" in template
    assert "Domain work" in template
    assert "Dependencies" in template


def test_scoped_software_requests_wait_for_the_governed_queue_worker():
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    queue = Path("../ingest/inventory/queue.py").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")

    assert "process_demand_entry" not in main
    assert "run_software_scoped" not in main
    assert "process_demand_entry" not in queue
    assert "client, _DEMAND_TABLE, batch_size, job_run_id" in queue
    assert "Direct scoped software run" not in jobs_template
