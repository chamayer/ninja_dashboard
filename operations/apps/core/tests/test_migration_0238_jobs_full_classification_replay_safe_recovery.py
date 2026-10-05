"""Static contract checks for full classifier replay-safe recovery."""

import importlib


def test_full_classifier_recovery_requires_its_reviewed_immutable_revision():
    migration = importlib.import_module(
        "apps.core.migrations.0238_jobs_full_classification_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0237_jobs_kev_replay_safe_recovery")
    ]
    assert "software-classify-full" in migration.FORWARD_SQL
    assert "job_recovery_policy_authorities" in migration.FORWARD_SQL
    assert "82349c35e905f3414277ae04243d00e169ea79cb2f0c16dbec1473f3d77025bf" in migration.FORWARD_SQL
