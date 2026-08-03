from __future__ import annotations

import pytest

software = pytest.importorskip("ingest.inventory.software")


class _Cursor:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


class _Connection:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> _Cursor:
        return _Cursor(self.statements)


class _Pool:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def connection(self) -> _Connection:
        return _Connection(self.statements)


def test_software_read_models_refresh_in_dependency_order(monkeypatch) -> None:
    pool = _Pool()
    monkeypatch.setattr(software.db, "pool", pool)

    software.refresh_read_models()

    assert pool.statements == [
        "REFRESH MATERIALIZED VIEW CONCURRENTLY operations.software_title_current",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY operations.v_software_safety",
    ]
