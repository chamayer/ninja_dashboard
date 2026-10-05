"""Static contract checks for KEV replay-safe recovery."""

import importlib


def test_kev_recovery_requires_its_reviewed_immutable_definition_revision():
    migration = importlib.import_module(
        "apps.core.migrations.0237_jobs_kev_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0236_jobs_replay_safe_recovery")
    ]
    assert "intel-kev" in migration.FORWARD_SQL
    assert "job_recovery_policy_authorities" in migration.FORWARD_SQL
    assert "job_recovery_policies" in migration.FORWARD_SQL
    assert "02b8fb3386e13d04ce90e54e1d7253591d9fcee85e98edea9413935b66fd0ade" in migration.FORWARD_SQL
