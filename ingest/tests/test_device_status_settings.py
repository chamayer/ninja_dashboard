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
    assert "device_status_settings.device_offline_days(cur, tenant_id, subject_id)" in (
        _INGEST / "patch_findings.py"
    ).read_text(encoding="utf-8")
    assert "device_status_settings.load(cur, tenant_id)[0]" in inspect.getsource(
        software_readiness._offline_days
    )
    assert "patch_activity_days" not in inspect.getsource(software_readiness)
    assert patch_findings  # imported to prove the module still loads


class _Cursor:
    """Answers the helper's queries from fixed data."""

    def __init__(self, column_exists=True, clients=None, devices=None, config=None):
        self.column_exists, self.clients = column_exists, clients or []
        self.devices, self.config, self.last = devices or [], config, ""

    def execute(self, sql, params=None):
        self.last = " ".join(sql.split())

    def fetchone(self):
        if "information_schema.columns" in self.last:
            return (self.column_exists,)
        if "evaluator_config" in self.last:
            return (self.config,) if self.config is not None else None
        return None

    def fetchall(self):
        if "FROM operations.clients c" in self.last:
            return self.clients
        return self.devices


def test_before_the_column_exists_nothing_is_overridden_and_sql_does_not_name_it():
    cursor = _Cursor(column_exists=False)
    assert device_status_settings.override_expression(cursor) == "NULL::integer"
    assert device_status_settings.client_overrides(cursor, 1) == {}
    assert device_status_settings.device_overrides(cursor, 1) == {}


def test_once_the_column_exists_sql_reads_it():
    assert device_status_settings.override_expression(_Cursor(), "c") == "c.offline_after_days"


def test_computers_inherit_their_clients_override():
    cursor = _Cursor(clients=[("client-a", 3)], devices=[("dev-1", "client-a"), ("dev-2", "client-b")])
    assert device_status_settings.client_overrides(cursor, 1) == {"client-a": 3}
    cursor = _Cursor(clients=[("client-a", 3)], devices=[("dev-1", "client-a"), ("dev-2", "client-b")])
    assert device_status_settings.device_overrides(cursor, 1) == {"dev-1": 3}


def test_readiness_uses_each_computers_own_threshold():
    from datetime import datetime, timedelta, timezone

    from ingest import software_readiness

    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    contacts = {"a": now - timedelta(days=5), "b": now - timedelta(days=5)}
    states = {}
    for device, days in (("a", None), ("b", 3)):
        override = {} if days is None else {device: days}
        states[device] = software_readiness.offline_readiness(
            [contacts[device]], now=now, offline_days=override.get(device, 7)
        )[0].value
    # Same silence: 5 days is fine at 7, but offline for the client that set 3.
    assert states == {"a": "ready", "b": "blocked"}


def test_evaluator_queries_use_the_client_value_with_the_tenant_value_as_fallback():
    source = (_INGEST / "evaluator.py").read_text(encoding="utf-8")
    assert source.count("make_interval(days => COALESCE({client_days}, %s))") == 2
    assert "client_offline_days.get(" in source
    assert "max(retire_review_days, device_offline_days + 1)" in source
    assert "offline_days_by_device" in (_INGEST / "software_readiness.py").read_text(encoding="utf-8")
