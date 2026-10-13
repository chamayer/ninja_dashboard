from __future__ import annotations

from contextlib import contextmanager

from ingest.inventory import queue


class _Cursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = ()) -> None:
        self.statements.append((sql, params))

    def fetchall(self):
        return [(7, "id=42", 0, 3), (8, "id=43", 1, 3)]


def test_claim_derives_attempt_numbers_from_recorded_history(monkeypatch):
    cur = _Cursor()

    @contextmanager
    def _fake_cursor():
        yield cur

    monkeypatch.setattr(queue, "_tenant_cursor", _fake_cursor)
    entries = queue.claim("run-1")

    assert [(e.id, e.ninja_device_id) for e in entries] == [(7, 42), (8, 43)]
    sql, params = cur.statements[1]
    # A lease-recovered entry keeps its attempts counter while the attempt is
    # already recorded; the insert must continue after the highest recorded one.
    assert "max(attempt_number)" in sql
    assert "GREATEST(claimed.attempts + 1" in sql
    assert params["ids"] == [7, 8]
    assert params["attempts"] == [0, 1]
    assert params["keys"] == ["7", "8"]
    assert params["kind"] == "software.activity"


def test_only_single_computer_requests_are_usable():
    assert queue.Entry(1, "id=12", 0, 3).ninja_device_id == 12
    assert queue.Entry(1, "org=5", 0, 3).ninja_device_id is None
    assert queue.Entry(1, "id=1 or 1=1", 0, 3).ninja_device_id is None
