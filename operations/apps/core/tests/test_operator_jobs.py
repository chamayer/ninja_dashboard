from pathlib import Path

from django.template.loader import get_template


def test_jobs_keep_durable_queue_and_terminal_step_contracts():
    queue = Path("../ingest/operator_job_queue.py").read_text(encoding="utf-8")
    migration = Path("apps/core/migrations/0244_jobs_operation_entrypoints.py").read_text(
        encoding="utf-8"
    )

    assert "operations.jobs_claim_next_v6" in queue
    assert "operations.jobs_finish_v1" in queue
    assert "_admit_workflow" in queue
    assert "A run is one executable step, not a workflow coordinator." in migration
    assert "status = p_status" in migration
    assert "jobs_propagate_dependency_terminal_v1" in migration


def test_jobs_present_one_list_detail_and_configuration_surface():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    detail_template = Path("templates/admin_job_detail.html").read_text(encoding="utf-8")
    configuration_template = Path("templates/admin_jobs_control_plane.html").read_text(
        encoding="utf-8"
    )
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert "def admin_job_detail" in views
    assert "def _operator_run_wait_explanation" in views
    assert "def admin_job_status" in views
    assert 'return redirect("admin_jobs")' in views
    assert "admin_job_detail" in urls
    assert "<th>Status</th>" in jobs_template
    assert "Status: {{ job.status_label }}" in jobs_template
    assert '{{ job.latest_at_label }} {{ job.latest_at|date:"M j, Y, g:i A" }}' in jobs_template
    assert "resource_blockers" in jobs_template
    assert "Last completed:" in views
    assert '"start_description": job.start_description' in views
    assert "_jobs_diagnostic_all(\"schedules\", cur)" in views
    assert "FROM operations.job_schedules" not in views[views.index("def admin_jobs("):views.index("def admin_jobs_run(")]
    assert "json.loads(row[1]) if isinstance(row[1], str)" in views
    assert "Job settings" in jobs_template
    assert "Run history" in detail_template
    assert "Waiting for" in detail_template
    assert "Starts after this" in detail_template
    assert "Job settings" in configuration_template
    assert "Jobs control plane" not in configuration_template
    get_template("admin_jobs.html")
    get_template("admin_job_detail.html")
    get_template("admin_jobs_control_plane.html")


def test_jobs_use_safe_existing_controls():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    detail_template = Path("templates/admin_job_detail.html").read_text(encoding="utf-8")

    assert "def admin_job_cancel" in views
    assert "def admin_job_retry" in views
    assert "def admin_job_bulk_cancel" in views
    assert "jobs_cancel_v1" in views
    assert "job-bulk-action" in jobs_template
    assert "Request stop" in jobs_template
    assert "Run now" in detail_template
    assert "Retry" in detail_template


def test_admin_navigation_separates_jobs_services_health_and_settings():
    base_template = Path("templates/base.html").read_text(encoding="utf-8")
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    overview_template = Path("templates/operations_admin_overview.html").read_text(
        encoding="utf-8"
    )
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    health_template = Path("templates/findings_admin_health.html").read_text(
        encoding="utf-8"
    )
    services_template = Path("templates/admin_services.html").read_text(encoding="utf-8")
    settings_template = Path("templates/admin_settings.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    for label in ("Overview", "Sources", "Jobs", "Services", "Health", "Settings"):
        assert f">{label}</a>" in base_template
    assert "Software decisions" not in base_template
    assert "admin_services" in urls
    assert "admin_settings" in urls
    assert "Needs attention" in overview_template
    assert "Overall Operations health" in overview_template
    assert "Platform summary" in overview_template
    assert "Recent administrator activity" in overview_template
    assert "health.domains" in overview_template
    assert "Health by area" in health_template
    assert "def _admin_health_snapshot" in views
    assert "def _operations_admin_overview_snapshot" in views
    assert "SET LOCAL operations.tenant_id = 1" in views
    assert 'finding_type__name="source_failure"' in views
    assert "actor_kind=AuditLog.ActorKind.USER" in views
    assert "occurrence_count=Count(\"id\")" in views
    assert 'next_due_at = parse_datetime(next_due_at)' in views
    assert "Next: {{ job.next_due_at" in jobs_template
    assert "Request stop for selected Jobs" in jobs_template
    assert "job.active_run and job.state == 'running'" in jobs_template
    assert views.count("health = _admin_health_snapshot") == 2
    assert 'finding_type__category__name="platform_health"' in views
    assert "Deployment owns their lifecycle" in services_template
    assert "Django Admin" in settings_template
    get_template("admin_services.html")
    get_template("admin_settings.html")
