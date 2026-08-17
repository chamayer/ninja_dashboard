"""Unit coverage for the data-backed serial rejection registry."""

from __future__ import annotations

from ingest import normalize


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchall(self):
        return self.rows


def test_explicit_serial_rejections_are_loaded_from_registry(monkeypatch) -> None:
    monkeypatch.setattr(normalize, "_serial_rejection_cache", None)
    cur = _Cursor([("default string",), ("system serial number",)])

    normalize.load_identity_value_rejections(cur)

    assert not normalize.is_usable_serial("Default string")
    assert not normalize.is_usable_serial("system serial number")
    assert not normalize.is_usable_serial("FFFFFFFF")
    assert normalize.is_usable_serial("real-serial-1234")
    assert any("identity_value_rejections" in sql for sql in cur.executed)


def test_serial_matching_fails_closed_until_rejection_registry_loads(monkeypatch) -> None:
    monkeypatch.setattr(normalize, "_serial_rejection_cache", None)

    assert not normalize.is_usable_serial("real-serial-1234")
