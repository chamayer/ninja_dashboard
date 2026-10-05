"""Static contract checks for collection replay-safe recovery."""

import importlib


def test_collection_recovery_requires_reviewed_immutable_revisions():
    migration = importlib.import_module(
        "apps.core.migrations.0240_jobs_collection_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0239_jobs_nvd_replay_safe_recovery")
    ]
    assert "intel-cpe-dict" in migration.FORWARD_SQL
    assert "patches" in migration.FORWARD_SQL
    assert "a7ac5b98c5463bccbd7c4840e5f1fa4cbf674966e2610f88693b2e37085e4406" in migration.FORWARD_SQL
    assert "e5b4ca4ad5c9f25c61f7056ecf32331a7daa9bd9aff2e486af478191f7f0c17c" in migration.FORWARD_SQL
