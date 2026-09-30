import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_source_domain_links_are_tenant_safe_and_rls_protected():
    migration = importlib.import_module(
        "apps.core.migrations.0218_jobs_domain_queue_tenant_links"
    )
    sql = migration.FORWARD_SQL

    assert "source_run_queue ADD COLUMN tenant_id BIGINT" in sql
    assert sql.count("FOREIGN KEY (tenant_id, job_run_id)") == 2
    assert "source_run_queue FORCE ROW LEVEL SECURITY" in sql
    assert "source_action_requests FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('operations.tenant_id', TRUE)" in sql


def test_source_domain_workers_attach_the_claiming_job_run():
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    demand = (ROOT / "ingest" / "source_run_queue.py").read_text(encoding="utf-8")
    actions = (ROOT / "ingest" / "source_actions.py").read_text(encoding="utf-8")

    assert "def _run_source_demand(job_run_id: object)" in queue
    assert "source_run_queue.process_next(job_run_id)" in queue
    assert "def _run_source_actions(job_run_id: object)" in queue
    assert "process_pending(job_run_id=job_run_id)" in queue
    assert "job_run_id = %s" in demand
    assert "job_run_id = %s" in actions
    assert 'SET LOCAL operations.tenant_id = 1' in demand
    assert 'SET LOCAL operations.tenant_id = 1' in actions
