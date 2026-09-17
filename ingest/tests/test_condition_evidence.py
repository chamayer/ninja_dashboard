from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingest.condition_evidence import (
    complete_snapshot_available,
    device_identity_signal,
    device_identity_signals,
    offline_readiness,
)


NOW = datetime(2026, 9, 16, tzinfo=UTC)


class Cursor:
    def __init__(self, row):
        self.row = row

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


def test_complete_snapshot_requires_consistent_counts_and_time():
    row = ("complete", True, 10, 10, 0, NOW - timedelta(minutes=2), NOW)
    assert complete_snapshot_available(Cursor(row), 1, "source", now=NOW)


def test_failed_or_future_snapshot_is_not_evidence():
    failed = ("failed", True, 10, 10, 1, NOW - timedelta(minutes=2), NOW)
    future = ("complete", True, 10, 10, 0, NOW, NOW + timedelta(minutes=1))
    assert not complete_snapshot_available(Cursor(failed), 1, "source", now=NOW)
    assert not complete_snapshot_available(Cursor(future), 1, "source", now=NOW)


def test_old_snapshot_is_not_current_even_when_complete():
    old = ("complete", True, 10, 10, 0, NOW - timedelta(days=2), NOW - timedelta(days=2))
    assert not complete_snapshot_available(Cursor(old), 1, "source", now=NOW)


def test_device_identity_signal_requires_attachment_and_no_conflict():
    ready = device_identity_signal(Cursor((True, False)), 1, "device")
    blocked = device_identity_signal(Cursor((True, True)), 1, "device")
    unknown = device_identity_signal(Cursor(None), 1, "device")

    assert ready.readiness.value == "ready"
    assert ready.reason == "identity:stable_attachment"
    assert blocked.readiness.value == "blocked"
    assert blocked.reason == "identity:unsettled_group"
    assert unknown.readiness.value == "unknown"
    assert unknown.reason == "identity:readiness_not_measured"


def test_batch_identity_evidence_preserves_unknown_and_blocked_states():
    rows = [("d1", True, False), ("d2", True, True)]
    signals = device_identity_signals(Cursor(rows), 1, ["d1", "d2", "d3"])
    assert signals["d1"].readiness.value == "ready"
    assert signals["d2"].readiness.value == "blocked"


def test_offline_readiness_uses_contact_timestamps_and_fails_closed():
    recent = NOW - timedelta(hours=1)
    old = NOW - timedelta(days=8)
    assert offline_readiness([recent], now=NOW, offline_days=7)[0].value == "ready"
    assert offline_readiness([old], now=NOW, offline_days=7)[0].value == "blocked"
    assert offline_readiness([None], now=NOW, offline_days=7)[0].value == "unknown"
    assert offline_readiness([NOW + timedelta(minutes=1)], now=NOW, offline_days=7)[0].value == "unknown"
