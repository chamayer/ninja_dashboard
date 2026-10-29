"""Ingest findings writers take the guard and wait for contract 4 (PLAN-003 R2)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from ingest import db
from shared.findings_contract import FINDING_CONTRACT

ROOT = Path(__file__).parents[1]


def test_findings_transaction_takes_the_guard_before_anything_else():
    cursor = mock.MagicMock()
    connection = mock.MagicMock()
    connection.__enter__.return_value.cursor.return_value.__enter__.return_value = (
        cursor
    )
    pool = mock.Mock()
    pool.connection.return_value = connection
    with mock.patch.object(db, "pool", pool):
        with db.findings_transaction(1) as cur:
            cur.execute("SELECT 1")
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "set_config('operations.finding_contract'" in statements[0]
    assert "acquire_tenant_guard" in statements[1]
    assert statements[2] == "SELECT 1"


def test_wait_for_contract_admits_work_only_once_the_contract_matches():
    answers = iter([None, FINDING_CONTRACT - 1, FINDING_CONTRACT])
    with (
        mock.patch.object(db, "transaction") as transaction,
        mock.patch.object(
            db, "database_findings_contract", side_effect=lambda cur: next(answers)
        ),
        mock.patch.object(db.time, "sleep") as sleep,
    ):
        transaction.return_value.__enter__.return_value = object()
        db.wait_for_findings_contract(poll_seconds=0)
    assert sleep.call_count == 2


def test_evaluator_takes_the_session_guard_before_its_snapshot():
    source = (ROOT / "evaluator.py").read_text(encoding="utf-8")
    body = source[
        source.index("def _evaluation_transaction") : source.index(
            "class LifecycleResult"
        )
    ]
    assert body.index("lock_tenant_session") < body.index("REPEATABLE READ")
    assert "unlock_tenant_session" in body


def test_startup_waits_for_the_contract_before_admitting_work():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    worker = (ROOT / "jobs_worker.py").read_text(encoding="utf-8")
    assert main.index("db.wait_for_findings_contract()") < main.index(
        "operator_job_queue.register_definition_snapshots()"
    )
    assert worker.index("db.wait_for_findings_contract()") < worker.index(
        "operator_job_queue.replay_interrupted_runs()"
    )


def test_findings_producers_open_guarded_transactions():
    for relative, count in (
        ("cmdb_findings.py", 1),
        ("patch_findings.py", 1),
        ("platform_findings.py", 1),
        ("intel/windows_servicing.py", 1),
        ("software_reconcile.py", 2),
        ("identity/client_resolver.py", 1),
        ("identity/resolver.py", 5),
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert source.count("db.findings_transaction(") == count, relative


def test_findings_upserts_use_the_namespace_conflict_target():
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "ON CONFLICT (tenant_id, condition_key)" not in source, path
        assert "INSERT INTO operations.admin_findings" not in source, path
