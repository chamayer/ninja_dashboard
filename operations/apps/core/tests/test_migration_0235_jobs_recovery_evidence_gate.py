"""Static contract checks for the Jobs uncertain-recovery permission gate."""

import importlib


def test_uncertain_claim_release_is_not_an_operations_app_capability():
    migration = importlib.import_module(
        "apps.core.migrations.0235_jobs_recovery_evidence_gate"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0234_fix_jobs_activity_relations_api")
    ]
    assert "REVOKE EXECUTE ON FUNCTION operations.jobs_release_contained_claim_v1" in migration.FORWARD_SQL
    assert "FROM operations_app" in migration.FORWARD_SQL
