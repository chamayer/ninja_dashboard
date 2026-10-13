from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ingest import platform_findings as pf

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows, table_exists=True):
        self.rows = rows
        self.table_exists = table_exists
        self.last = ""

    def execute(self, sql, params=None):
        self.last = sql

    def fetchone(self):
        return (self.table_exists,)

    def fetchall(self):
        return self.rows


def test_each_held_computer_is_one_admin_finding(monkeypatch):
    device = uuid.uuid4()
    rows = [(device, "PC-1", NOW, "Ninja listed 3 programs", 120, 3, None)]
    emitted, assessed = [], []
    monkeypatch.setattr(pf, "_upsert_admin_finding", lambda cur, **kw: emitted.append(kw) or "f1")
    monkeypatch.setattr(pf, "_record_platform_assessment",
                        lambda *args, **kw: assessed.append(args[3]))
    counts = {"software_inventory_held": 0}

    keys = pf._eval_inventory_holds(_Cursor(rows), 77, NOW, counts, dry_run=False)

    assert keys == [f"software_inventory_held:{device}"]
    assert counts["software_inventory_held"] == 1
    assert emitted[0]["finding_type_id"] == 77
    assert emitted[0]["details"]["previous_program_count"] == 120
    assert emitted[0]["subject_ref"]["device_id"] == str(device)
    assert assessed == ["software_inventory_held"]


def test_nothing_is_emitted_before_the_type_or_table_exists(monkeypatch):
    monkeypatch.setattr(pf, "_upsert_admin_finding", lambda *a, **k: 1 / 0)
    counts = {"software_inventory_held": 0}
    assert pf._eval_inventory_holds(_Cursor([]), None, NOW, counts, dry_run=False) == []
    assert pf._eval_inventory_holds(_Cursor([], table_exists=False), 77, NOW, counts,
                                    dry_run=False) == []
