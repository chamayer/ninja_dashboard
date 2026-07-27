"""Retention routes through the security-definer purge function.

The "never delete an open version" invariant lives in migration 0074
(`operations.purge_closed_observation_history`). To keep the invariant
uncircumventable from Python, this test asserts that `purge_all()` calls
that function by name rather than issuing a raw DELETE.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ingest import retention_observations


class _MockCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (0, 0)


class _MockTxn:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return self._cur

    def __exit__(self, *_):
        return False


def test_purge_all_calls_security_definer_function():
    cur = _MockCursor()
    with patch("ingest.retention_observations.db.transaction",
               return_value=_MockTxn(cur)):
        retention_observations.purge_all(days=90)

    calls = [sql for sql, _ in cur.executed]
    assert any("operations.purge_closed_observation_history" in sql
               for sql in calls), (
        "Retention must route through the security-definer function; "
        f"got: {calls!r}"
    )
    assert not any("DELETE FROM operations.entity_observation_history" in sql
                   for sql in calls), (
        "Retention must not issue raw DELETE — the security-definer function "
        "is the guard against removing open SCD-2 versions."
    )
    assert not any("DELETE FROM operations.software_installation_history"
                   in sql for sql in calls)


def test_purge_all_passes_cutoff_and_returns_counts():
    cur = MagicMock()
    cur.fetchone.return_value = (7, 3)
    with patch("ingest.retention_observations.db.transaction",
               return_value=_MockTxn(cur)):
        generic, software = retention_observations.purge_all(days=30)
    assert (generic, software) == (7, 3)
    # First (and only) execute is the function call.
    call_sql, call_params = cur.execute.call_args_list[0].args
    assert "operations.purge_closed_observation_history" in call_sql
    assert len(call_params) == 1
    # Cutoff must be a real datetime, not a string.
    from datetime import datetime
    assert isinstance(call_params[0], datetime)
