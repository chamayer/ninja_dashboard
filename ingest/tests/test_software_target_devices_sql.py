from __future__ import annotations

from contextlib import contextmanager

from ingest import software_findings as sf


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return (0,)


class _Pool:
    def __init__(self, cur: _Cursor) -> None:
        self._cur = cur

    @contextmanager
    def connection(self):
        cur = self._cur

        class _Conn:
            @contextmanager
            def cursor(self):
                yield cur

        yield _Conn()


def _ready(monkeypatch) -> None:
    monkeypatch.setattr(sf, "_incremental_markers_ready", lambda cur: True)
    monkeypatch.setattr(sf, "_table_exists", lambda cur, name: True)
    monkeypatch.setattr(sf, "_column_exists", lambda cur, table, column: True)
    monkeypatch.setattr(sf, "_empty_reclassification_targets", lambda cur, tenant: [])


def test_target_join_is_two_hashable_equality_joins():
    sql = sf._TARGET_DEVICES_SQL
    # An OR between the version and title match cannot be hashed; it compared
    # every installation with every open target.
    assert "OR (target.software_version_id IS NULL" not in sql
    assert "installation.software_version_id = target.software_version_id" in sql
    assert "LOWER(installation.canonical_name) = target.canonical_name" in sql
    assert "AND target.software_version_id IS NULL" in sql  # title match only for title targets
    assert sql.count("%s") == 2


def test_selection_passes_one_tenant_per_placeholder(monkeypatch):
    _ready(monkeypatch)
    cur = _Cursor()
    sf._incremental_selection(cur, 1)
    sql, params = cur.calls[0]
    assert sql.count("%s") == len(params)
    assert params[-1] == sf._INCREMENTAL_DEVICE_BATCH_SIZE


def test_pending_count_passes_one_tenant_per_placeholder(monkeypatch):
    _ready(monkeypatch)
    cur = _Cursor()
    monkeypatch.setattr(sf.db, "pool", _Pool(cur), raising=False)
    assert sf.incremental_pending_count(1) == 0
    sql, params = cur.calls[-1]
    assert sql.count("%s") == len(params)
