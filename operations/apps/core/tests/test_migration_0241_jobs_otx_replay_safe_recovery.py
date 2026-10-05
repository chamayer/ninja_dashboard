"""Static contract checks for OTX replay-safe recovery."""

import importlib


def test_otx_recovery_requires_the_reviewed_immutable_revision():
    migration = importlib.import_module(
        "apps.core.migrations.0241_jobs_otx_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0240_jobs_collection_replay_safe_recovery")
    ]
    assert "intel-otx" in migration.FORWARD_SQL
    assert "job_recovery_policy_authorities" in migration.FORWARD_SQL
    assert "job_recovery_policies" in migration.FORWARD_SQL
    assert "5046b33141f7403898d0d20f8e68ab84055b87b8e8bf493269b30913be1e687b" in migration.FORWARD_SQL
