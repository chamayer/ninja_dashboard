import importlib
import re

from shared.jobs_registry import REPLAY_SAFE_RECOVERY_EVIDENCE

EXTERNAL_EFFECT_JOBS = {
    "notifications-dispatch",
    "notifications-digest",
    "source-actions",
    "retention-history",
}


def _migration():
    return importlib.import_module("apps.core.migrations.0280_jobs_local_work_replay_safe_recovery")


def _approved() -> dict[str, str]:
    rows = re.findall(
        r"\(1, '([a-z-]+)', 'replay_safe', '((?:[^']|'')*)'\)", _migration().FORWARD_SQL
    )
    return {key: text.replace("''", "'") for key, text in rows}


def test_each_approved_job_matches_its_registry_evidence():
    approved = _approved()

    assert len(approved) == 12
    # Migration 0285 restates the two inventory Jobs' evidence after the
    # inventory rebuild; its own test checks those against the registry.
    restated = {"software-queue-drain", "software-enqueue-orgs"}
    # Parity check was retired with agent compliance (PLAN-022).
    retired = {"parity-check"}
    for key, evidence in approved.items():
        if key not in restated | retired:
            assert REPLAY_SAFE_RECOVERY_EVIDENCE[key] == evidence


def test_jobs_with_external_effects_keep_manual_review():
    approved = set(_approved())

    assert not approved & EXTERNAL_EFFECT_JOBS
    assert not EXTERNAL_EFFECT_JOBS & set(REPLAY_SAFE_RECOVERY_EVIDENCE)


def test_migration_follows_0279():
    assert _migration().Migration.dependencies == [
        ("operations", "0279_jobs_dependency_accepts_merged_software_run")
    ]
