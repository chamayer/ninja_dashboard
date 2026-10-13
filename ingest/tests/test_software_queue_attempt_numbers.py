from __future__ import annotations

from contextlib import contextmanager

from ingest.inventory import queue


class _Cursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append((sql, params))

    def fetchone(self):
        return (7, "df", 0, 3)


def test_claim_derives_attempt_number_from_recorded_history(monkeypatch):
    cur = _Cursor()

    @contextmanager
    def _fake_cursor():
        yield cur

    monkeypatch.setattr(queue, "_tenant_cursor", _fake_cursor)
    entry = queue._claim_one("ninja_core.software_activity_queue", "run-1")

    assert entry == {"id": 7, "df": "df", "attempts": 0, "max_attempts": 3}
    sql, params = cur.statements[1]
    # A lease-recovered entry keeps attempts=0 while attempt 1 is already
    # recorded; the insert must continue after the highest recorded attempt.
    assert "max(attempt_number)" in sql
    assert "FROM operations.job_domain_attempts" in sql
    assert params[2] == 1  # floor from the entry counter
    assert params[1] == "7"
