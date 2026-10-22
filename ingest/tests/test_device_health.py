from __future__ import annotations

import importlib
import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

pytest.importorskip("httpx")
device_health = importlib.import_module("ingest.core.device_health")


def _health_record() -> dict:
    return {
        "deviceId": 42,
        "pendingRebootReason": "WINDOWS_UPDATE",
        "failedOSPatchesCount": 1,
        "pendingOSPatchesCount": 2,
        "failedSoftwarePatchesCount": 3,
        "pendingSoftwarePatchesCount": 4,
        "alertCount": 5,
        "activeJobCount": 6,
        "healthStatus": "WARNING",
        "activeThreatsCount": 7,
        "quarantinedThreatsCount": 8,
        "blockedThreatsCount": 9,
        "criticalVulnerabilityCount": 10,
        "highVulnerabilityCount": 11,
        "mediumVulnerabilityCount": 12,
        "lowVulnerabilityCount": 13,
        "installationIssuesCount": 14,
        "offline": False,
        "parentOffline": True,
        "productsInstallationStatuses": {"agent": "INSTALLED"},
    }


def test_health_row_projects_all_typed_material_state():
    observed_at = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
    row = device_health._to_row(_health_record(), observed_at)
    canonical = device_health._canonical_health(row, "agent.rmm")

    assert canonical["entity_type"] == "agent.rmm"
    assert canonical["pending_reboot_reason"] == "WINDOWS_UPDATE"
    assert canonical["pending_os_patches_count"] == 2
    assert canonical["offline"] is False
    assert canonical["parent_offline"] is True
    assert canonical["products_installation_statuses"] == {
        "agent": "INSTALLED",
    }


def test_zero_known_health_rows_fail_closed(monkeypatch):
    class EmptyClient:
        @staticmethod
        def paginate_cursor(_path):
            return iter(())

    @contextmanager
    def fake_run_log(_domain):
        yield {"rows_upserted": 0, "rows_inserted": 0}

    monkeypatch.setattr(device_health, "run_log", fake_run_log)
    monkeypatch.setattr(device_health, "_fetch_known_devices", lambda: {42: "WINDOWS"})

    with pytest.raises(RuntimeError, match="zero known devices"):
        device_health.run(
            EmptyClient(),
            datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        )


def test_distinct_health_namespace_and_scope_are_not_device_scope():
    assert device_health.NINJA_HEALTH_EXTERNAL_NAMESPACE == "device-health"
    assert device_health.NINJA_HEALTH_SNAPSHOT_SCOPE == "Ninja.device-health"
    assert device_health._legacy_health_entity_key("42") == "device-health:42"


def test_normal_health_collection_does_not_write_legacy_snapshots() -> None:
    assert "ninja_core.device_health_snapshots" not in inspect.getsource(
        device_health.run
    )


def test_health_links_through_the_ninja_source_instance(monkeypatch) -> None:
    class Cursor:
        def __init__(self):
            self.executed: list[tuple[str, object]] = []

        def execute(self, statement, params=None):
            self.executed.append((statement, params))

        def fetchone(self):
            return (True,)

        @staticmethod
        def fetchall():
            return [("42", device_id, client_id)]

    cursor = Cursor()
    device_id = uuid4()
    client_id = uuid4()
    source_instance_id = uuid4()
    run_id = uuid4()

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr(device_health.db, "transaction", transaction)
    monkeypatch.setattr(
        device_health,
        "begin_run",
        lambda *_args, **_kwargs: (run_id, source_instance_id),
    )
    monkeypatch.setattr(
        device_health, "write_current_rows", lambda _cur, rows: len(rows)
    )
    monkeypatch.setattr(device_health, "complete_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(device_health, "reconcile_complete_run", lambda *_args: None)

    observed_at = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    assert (
        device_health._write_health_observations(
            [device_health._to_row(_health_record(), observed_at)],
            {42: _health_record()},
            {42: "WINDOWS_WORKSTATION"},
            observed_at,
        )
        == 1
    )

    source_query, params = cursor.executed[-1]
    assert "o.source_instance_id = %s" in source_query
    assert "o.source_id" not in source_query
    assert params == (1, source_instance_id, ["42"])
