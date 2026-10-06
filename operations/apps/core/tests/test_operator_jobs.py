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
    assert "Latest status" in jobs_template
    assert "Job configuration" in jobs_template
    assert "Run history" in detail_template
    assert "Waiting for" in detail_template
    assert "Starts after this" in detail_template
    assert "Job configuration" in configuration_template
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
