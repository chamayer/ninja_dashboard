"""Static contract checks for NVD replay-safe recovery."""

import importlib


def test_nvd_recovery_requires_its_reviewed_immutable_revision():
    migration = importlib.import_module(
        "apps.core.migrations.0239_jobs_nvd_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0238_jobs_full_classification_replay_safe_recovery")
    ]
    assert "intel-nvd" in migration.FORWARD_SQL
    assert "job_recovery_policy_authorities" in migration.FORWARD_SQL
    assert "9d58d823a51043da124b6a2da9b867bdb3a740f4824458b470f3965bce333c46" in migration.FORWARD_SQL
