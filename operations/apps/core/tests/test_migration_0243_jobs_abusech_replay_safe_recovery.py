"""Static contract checks for abuse.ch replay-safe recovery."""

import importlib


def test_abusech_recovery_requires_the_reviewed_immutable_revision():
    migration = importlib.import_module(
        "apps.core.migrations.0243_jobs_abusech_replay_safe_recovery"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0242_jobs_current_work_activity")
    ]
    assert "intel-abusech" in migration.FORWARD_SQL
    assert "job_recovery_policy_authorities" in migration.FORWARD_SQL
    assert "job_recovery_policies" in migration.FORWARD_SQL
    assert "ce588955190b02582046a0f8dbfd671b91b2eb42674d0bf5b8f865b697be75bc" in migration.FORWARD_SQL
