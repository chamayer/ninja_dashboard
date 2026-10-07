import importlib


def test_contained_recovery_policy_only_covers_reviewed_interrupted_revisions():
    migration = importlib.import_module(
        "apps.core.migrations.0260_jobs_contained_recovery_policy"
    )
    sql = migration.FORWARD_SQL

    assert "job_recovery_policy_authorities" in sql
    assert "job_resource_claims" in sql
    assert "claim.state = 'contained'" in sql
    assert "run.status = 'stalled'" in sql
    assert "authority.recovery_mode = 'replay_safe'" in sql
    assert "ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING" in sql
