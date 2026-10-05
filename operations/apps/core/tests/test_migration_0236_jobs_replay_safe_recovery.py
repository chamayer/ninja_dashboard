"""Static contract checks for audited replay-safe Jobs recovery."""

import importlib


def test_recovery_policies_are_durable_audited_and_restricted_to_ingest():
    migration = importlib.import_module(
        "apps.core.migrations.0236_jobs_replay_safe_recovery"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0235_jobs_recovery_evidence_gate")
    ]
    assert "CREATE TABLE operations.job_recovery_policies" in sql
    assert "CREATE TABLE operations.job_recovery_policy_authorities" in sql
    assert "CREATE TABLE operations.job_recovery_assessments" in sql
    assert "intel-epss" in sql
    assert "software-classify-only" in sql
    assert "jobs_reconcile_replay_safe_containment_v1" in sql
    assert "assessment.run_id IS NULL" in sql
    assert "state = 'released'" in sql
    assert "TO ninja_ingest" in sql
    assert "jobs_recovery_diagnostics_v1" in sql
    assert "recovery_authorities" in sql
    assert "TO operations_app" in sql
