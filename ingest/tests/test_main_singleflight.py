from __future__ import annotations

from contextlib import contextmanager

import pytest

main = pytest.importorskip("ingest.main")


class _Cursor:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple) -> None:
        self.statements.append((statement, params))

    def fetchone(self) -> tuple[bool]:
        return (self.acquired,)


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, acquired: bool) -> None:
        self.cursor = _Cursor(acquired)

    def connection(self) -> _Connection:
        return _Connection(self.cursor)


@contextmanager
def _run_log(_domain: str):
    yield {}


def test_patch_cycle_skips_when_database_lock_is_held(monkeypatch) -> None:
    pool = _Pool(acquired=False)
    monkeypatch.setattr(main.db, "pool", pool)

    assert main.run_patching_once() is False
    assert [statement for statement, _ in pool.cursor.statements] == [
        "SELECT pg_try_advisory_lock(%s)"
    ]


def test_patch_cycle_releases_lock_after_success(monkeypatch) -> None:
    pool = _Pool(acquired=True)
    monkeypatch.setattr(main.db, "pool", pool)
    monkeypatch.setattr(main, "run_log", _run_log)
    monkeypatch.setattr(main, "_safe", lambda *_args: None)
    monkeypatch.setattr(main, "refresh_after_collection", lambda *_args: None)

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(main, "NinjaClient", Client)

    assert main.run_patching_once() is True
    assert pool.cursor.statements[-1][0] == "SELECT pg_advisory_unlock(%s)"


def test_patch_cycle_releases_lock_after_exception(monkeypatch) -> None:
    pool = _Pool(acquired=True)
    monkeypatch.setattr(main.db, "pool", pool)
    monkeypatch.setattr(main, "run_log", _run_log)

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(main, "NinjaClient", FailingClient)

    with pytest.raises(RuntimeError, match="boom"):
        main.run_patching_once()
    assert pool.cursor.statements[-1][0] == "SELECT pg_advisory_unlock(%s)"
