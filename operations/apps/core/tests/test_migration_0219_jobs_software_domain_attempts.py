import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_software_queue_attempts_are_immutable_and_tenant_safe():
    migration = importlib.import_module(
        "apps.core.migrations.0219_jobs_software_domain_attempts"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE TABLE operations.job_domain_attempts" in sql
    assert "immutable_job_domain_attempts" in sql
    assert "FOREIGN KEY (tenant_id, job_run_id)" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "software_scheduled_queue" in sql
    assert "software_demand_queue" in sql
    assert "software_activity_queue" in sql


def test_every_domain_claim_records_its_owning_job_attempt():
    software = (ROOT / "ingest" / "inventory" / "queue.py").read_text(
        encoding="utf-8"
    )
    demand = (ROOT / "ingest" / "source_run_queue.py").read_text(encoding="utf-8")
    actions = (ROOT / "ingest" / "source_actions.py").read_text(encoding="utf-8")
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")

    assert "INSERT INTO operations.job_domain_attempts" in software
    assert "INSERT INTO operations.job_domain_attempts" in demand
    assert "INSERT INTO operations.job_domain_attempts" in actions
    assert "main.run_software_queue_once(progress.job_id)" in queue
    assert 'SET LOCAL operations.tenant_id = 1' in software
