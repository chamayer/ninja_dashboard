"""Requirement verdicts are written only by the coverage pass; Python only audits them."""

from __future__ import annotations

import logging

from ingest import requirement_state


class _Cursor:
    def __init__(self, available=True, row_kind="tuple", drift=2):
        self.available = available
        self.row_kind = row_kind
        self.drift = drift
        self.executed = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))

    def fetchone(self):
        value = self.available if "to_regprocedure" in self._last else self.drift
        return {"value": value} if self.row_kind == "dict" else (value,)


def test_the_check_is_skipped_before_the_migration_lands():
    cursor = _Cursor(available=False)
    assert requirement_state.check_state(cursor, 1) == 0
    assert len(cursor.executed) == 1


def test_the_check_runs_for_the_tenant_and_reports_open_drift(caplog):
    for row_kind in ("tuple", "dict"):
        cursor = _Cursor(row_kind=row_kind, drift=3)
        with caplog.at_level(logging.WARNING):
            assert requirement_state.check_state(cursor, 1) == 3
        assert cursor.executed[-1] == (
            "SELECT operations.check_device_requirement_state(%s)",
            (1,),
        )
    assert "3 open disagreement" in caplog.text


def test_no_drift_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        assert requirement_state.check_state(_Cursor(drift=0), 1) == 0
    assert caplog.text == ""
