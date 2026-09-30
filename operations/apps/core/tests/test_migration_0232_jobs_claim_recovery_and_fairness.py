import importlib


def test_claim_recovery_preserves_uncertain_work_and_exposes_reviewed_release():
    migration = importlib.import_module(
        "apps.core.migrations.0232_jobs_claim_recovery_and_fairness"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0231_jobs_definition_priority_contract")
    ]
    assert "terminal Job retained a held claim" in sql
    assert "state = 'contained'" in sql
    assert "jobs_release_contained_claim_v1" in sql
    assert "Only a stalled Job can release contained claims" in sql
    assert "TO operations_app" in sql


def test_claim_v5_scans_past_resource_blocking_and_records_a_wait_reason():
    migration = importlib.import_module(
        "apps.core.migrations.0232_jobs_claim_recovery_and_fairness"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_claim_next_v5" in sql
    assert "FOR v_run IN" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "v_blocked := TRUE" in sql
    assert "CONTINUE;" in sql
    assert "Waiting for a protected resource held by earlier work." in sql
    assert "wait_category = NULL, wait_reason = NULL" in sql
    assert "timeout_minutes" in sql


def test_schedule_revision_conflict_becomes_a_durable_deferral_not_a_retry_loop():
    migration = importlib.import_module(
        "apps.core.migrations.0232_jobs_claim_recovery_and_fairness"
    )
    sql = migration.FORWARD_SQL

    assert "EXCEPTION WHEN raise_exception" in sql
    assert "v_message NOT LIKE 'Conflicting%'" in sql
    assert "'deferred'" in sql
    assert "incompatible retained Job request drains" in sql
