"""Static checks for the dedicated converted-Jobs worker topology."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_compose_worker_uses_the_ingest_image_without_an_http_port():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  jobs-worker:" in compose
    assert 'command: ["python", "-m", "ingest.jobs_worker"]' in compose
    assert "container_name: ninja-jobs-worker" in compose
    worker = compose.split("  jobs-worker:", 1)[1].split("  operations:", 1)[0]
    assert "ports:" not in worker
    assert '"--healthcheck"' in worker


def test_worker_uses_only_fenced_v1_queue_apis():
    worker = (ROOT / "ingest" / "jobs_worker.py").read_text(encoding="utf-8")
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")

    assert '"-m", "ingest.jobs_child"' in worker
    assert "_claim_next_v7(incarnation)" in worker
    assert "jobs_claim_next_v7" in queue
    assert "jobs_dispatch_ready_v1" in queue
    assert "jobs_record_v1_progress" in queue
    assert "jobs_finish_v1" in queue
    assert "jobs_should_cancel_v1" in queue
    assert "jobs_finish_cancelled_v1" in queue
    assert "_shutdown_children(children)" in worker
    assert "_interrupt_v1" in worker
    assert "child.process.stdout.read()" in worker
    assert "could not record the exited child result" in worker
    assert ".terminate(" not in worker
    assert ".kill(" not in worker
    assert "jobs_interrupt_v1" in queue
    assert "record_runtime_heartbeat" in worker
    assert "stop_runtime" in worker
    assert "JobProgressRejected" in worker
    assert "restarting supervisor" in worker
    assert "JobProgressRejected" in queue


def test_contained_work_keeps_data_safety_but_not_dead_execution_capacity():
    migration = (
        ROOT
        / "operations"
        / "apps"
        / "core"
        / "migrations"
        / "0271_jobs_contained_capacity_release.py"
    ).read_text(encoding="utf-8")
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")

    assert "jobs_release_contained_capacity_v1" in migration
    assert "NEW.resource_template LIKE 'capacity:%'" in migration
    assert "NEW.resource_template LIKE 'lane:%'" in migration
    assert "any affected data boundary remains protected" in migration
    assert "handler_version = %s" in queue
