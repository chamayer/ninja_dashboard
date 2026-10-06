from pathlib import Path

from django.template.loader import get_template


def test_operator_jobs_use_a_durable_queue_and_separate_stall_watchdog():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    migration = Path("apps/core/migrations/0178_operator_job_queue.py").read_text(encoding="utf-8")
    progress_migration = Path("apps/core/migrations/0179_add_operator_job_progress.py").read_text(encoding="utf-8")
    workflow_migration = Path("apps/core/migrations/0180_operator_job_workflow_controls.py").read_text(encoding="utf-8")
    software_lane_migration = Path("apps/core/migrations/0182_software_job_lane_and_operations_controls.py").read_text(encoding="utf-8")

    assert "operations.jobs_claim_next_v6" in queue
    assert "operations.jobs_finish_v1" in queue
    assert "operations.jobs_record_v1_progress" in queue
    assert "class V1JobProgress" in queue
    assert "_software_classify_with_intel" in queue
    assert "jobs_dispatch_ready_v1" in queue
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
    assert "jobs_claim_next_v6" in queue
    assert "software-classify-full" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "_queue_software_rebuild_after_commit" in Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT, UPDATE ON operations.operator_job_runs TO operations_app" in software_lane_migration
    assert "Superseded by a broader Software classifier run" in software_lane_migration


def test_jobs_status_uses_operator_language_and_safe_controls():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    template = Path("templates/admin_job_status.html").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert '"ready", "waiting", "running", "completed"' in views
    assert '"stalled": "Needs attention"' in views
    assert "def admin_job_cancel" in views
    assert "jobs_cancel_v1" in views
    assert "Request cancellation" in template
    assert "Cancellation pending" in template
    assert "Job activity" in template
    assert "Waiting for capacity" in views
    assert "Current work" in template
    assert "Updated" in template
    assert "Worker active" in template
    assert "Not started" in template
    assert "Waiting for protected work" in views
    assert "System activity" in template
    assert '"automatic": "Automatic"' in views
    assert '"dependency": "Dependency"' in views
    assert "Safety deadline" in template
    assert "Show error details" in template
    assert "admin_job_history_retry" in template
    assert "_HISTORY_RETRYABLE_KINDS" in views
    assert "admin_job_history_retry" in urls
    assert "admin_job_status" in urls
    assert "admin_job_retry" in urls
    assert "admin_job_bulk_cancel" in urls
    assert "def admin_job_bulk_cancel" in views
    assert "jobs_cancel_v1" in views
    assert "job-bulk-action" in template
    assert "Cancel selected / request cancellation" in template
    assert "Recovery review required" in template
    assert "escalate through the platform incident process" in template
    assert "admin_job_release_contained_claim" not in urls
    assert "def admin_job_release_contained_claim" not in views
    assert "queued_job_status" in views
    assert "operator_job_runs" in views
    assert "capability_state" in views
    assert "scheduled_definition_keys" in views
    assert 'status_entry = _JOB_INDEX.get(entry["id"], entry)' in views
    assert 'source = status_entry.get("status_source")' in views
    assert "FROM operations.job_schedules" in views
    assert "disabled_reason" in views
    assert "The durable Jobs queue is the history authority" in views
    assert "No recorded run yet" in jobs_template
    assert "No run available" in jobs_template
    assert "next due" in jobs_template
    assert "last_schedule_outcome" in jobs_template
    assert "jobs_activity_relations_v1" in views
    assert "jobs_activity_current_v1" in views
    assert "current_summary" in views
    assert "Current Job summary" in template
    assert "Needs attention" in template
    assert "latest_by_job" in views
    assert "latest active attempt" in template
    assert "Technical details" in template
    assert "Domain work" in template
    assert "Dependencies" in template
    assert "_admit_operator_workflow" in views
    assert "jobs_add_revision_dependency_v1" in views
    assert "_admit_workflow" in queue
    assert "jobs_add_revision_dependency_v1" in queue
    assert '"contract": item["contract"]' in views
    assert '"required_revision": item["required_revision"]' in views
    assert "Output revisions:" in template
    assert "output_revisions, request_payload" in views
    assert "output_revisions, requested_input" not in views
    assert "admin_jobs_control_plane" in urls
    assert "jobs_admin_diagnostics_v1" in views
    assert "jobs_activity_relations_v1" in views
    assert "_jobs_control_health" in views
    assert "recovery_authorities" in views
    assert "recovery_policies" in views
    assert "recovery_assessments" in views
    assert "jobs_recovery_diagnostics_v1" in views
    assert '"Recovery authority"' in views
    assert '"Recovery policy"' in views
    assert '"Recovery evidence"' in views
    control_template = Path("templates/admin_jobs_control_plane.html").read_text(encoding="utf-8")
    assert "row.items" in control_template
    assert "Runtime heartbeats" in views
    assert "Recovered automatically" in views
    assert "Recovery evidence" in template
    assert "Run history" in template
    control_start = views.index("def admin_jobs_control_plane")
    assert "@require_admin" in views[views.rfind("@login_required", 0, control_start):control_start]


def test_job_activity_has_complete_filtered_pagination_and_compiles():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/admin_job_status.html").read_text(encoding="utf-8")

    assert "SELECT count(*) FROM operations.operator_job_runs job" in views
    assert "LIMIT %s OFFSET %s" in views
    assert "job.status = ANY(%s::text[])" in views
    assert "current_only" in views
    assert "history_only" in views
    assert "SELECT count(*) FROM operations.run_log" in views
    assert "def _jobs_activity_date" in views
    assert "def _jobs_activity_query" in views
    for field in (
        "job", "scope", "origin", "status", "owner", "correlation",
        "batch", "from", "to", "technical",
    ):
        assert f'name="{field}"' in template
    assert "Durable Job activity pages" in template
    assert "System activity pages" in template
    assert "Origin / owner" in template
    get_template("admin_job_status.html")


def test_scoped_software_requests_wait_for_the_governed_queue_worker():
    main = Path("../ingest/main.py").read_text(encoding="utf-8")
    queue = Path("../ingest/inventory/queue.py").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")

    assert "process_demand_entry" not in main
    assert "run_software_scoped" not in main
    assert "process_demand_entry" not in queue
    assert "client, _DEMAND_TABLE, batch_size, job_run_id" in queue
    assert "Direct scoped software run" not in jobs_template


def test_jobs_control_plane_template_compiles():
    get_template("admin_jobs_control_plane.html")


def test_admin_health_links_jobs_findings_to_their_durable_evidence():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")

    assert 'details.get("job_run_id")' in views
    assert 'details.get("job_key")' in views
    assert 'details.get("control_section")' in views
    assert "control_plane_url" in template


def test_sources_surface_links_active_demand_to_its_durable_job_run():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/sources.html").read_text(encoding="utf-8")

    assert "job_run_id" in views[views.index("def sources_status"):]
    assert "active_job_url" in views
    assert "Open Job status" in template


def test_worker_reconciles_only_durable_replay_safe_containment_before_claiming_work():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    worker = Path("../ingest/jobs_worker.py").read_text(encoding="utf-8")

    assert "def reconcile_replay_safe_containment" in queue
    assert "jobs_reconcile_replay_safe_containment_v1" in queue
    assert (
        "register_definition_snapshots()\n"
        "    operator_job_queue.register_recovery_policies()\n"
        "    operator_job_queue.reconcile_replay_safe_containment()"
    ) in worker
    heartbeat = worker[worker.index("if now >= next_runtime_heartbeat:"):]
    assert "operator_job_queue.register_recovery_policies()" in heartbeat
    assert "operator_job_queue.reconcile_replay_safe_containment()" in heartbeat
