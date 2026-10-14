"""One "offline after" setting for every ingest consumer."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingest import device_status_settings, evaluator, patch_findings, software_readiness

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
_INGEST = Path(device_status_settings.__file__).parent


def test_defaults_when_nothing_is_saved():
    assert device_status_settings.thresholds(None) == (7, 30)
    assert device_status_settings.thresholds({}) == (7, 30)
    assert device_status_settings.thresholds({"active_device_days": "junk"}) == (7, 30)


def test_saved_values_are_used_and_retirement_review_always_follows_offline():
    assert device_status_settings.thresholds({"active_device_days": 3, "retire_review_days": 20}) == (3, 20)
    # Review for retirement cannot come before the computer is offline.
    assert device_status_settings.thresholds({"active_device_days": 40, "retire_review_days": 30}) == (40, 41)


def test_the_patch_data_freshness_setting_is_not_read_as_offline():
    assert device_status_settings.thresholds({"patch_activity_days": 90}) == (7, 30)


def test_lifecycle_aging_follows_the_tenant_thresholds():
    contact = {"status": "active", "at": NOW - timedelta(days=5)}
    assert evaluator._lifecycle_target(contact, NOW, 7, 30) == "active"
    assert evaluator._lifecycle_target(contact, NOW, 3, 30) == "offline_aging"
    assert evaluator._lifecycle_target(contact, NOW, 2, 4) == "pending_cleanup"


def test_no_consumer_uses_a_literal_or_the_policy_literal_for_offline():
    target = inspect.getsource(evaluator._lifecycle_target)
    assert "days=30" not in target and "days=7" not in target
    source = (_INGEST / "evaluator.py").read_text(encoding="utf-8")
    assert "policy.offline_days" not in source
    assert source.count("device_status_settings.load(") == 3
    assert "device_status_settings.load(cur, tenant_id)[0]" in (
        _INGEST / "patch_findings.py"
    ).read_text(encoding="utf-8")
    assert "device_status_settings.load(cur, tenant_id)[0]" in inspect.getsource(
        software_readiness._offline_days
    )
    assert "patch_activity_days" not in inspect.getsource(software_readiness)
    assert patch_findings  # imported to prove the module still loads
