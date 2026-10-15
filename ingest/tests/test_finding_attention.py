"""Finding state is written only by database triggers; Python only audits it."""

from __future__ import annotations

import re
from pathlib import Path

from ingest import finding_attention

ROOT = Path(__file__).resolve().parents[2]


class _Cursor:
    def __init__(self, available=True, row_kind="tuple", drift=2):
        self.available = available
        self.row_kind = row_kind
        self.drift = drift
        self.executed = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = " ".join(sql.split())
        self.executed.append(self._last)

    def fetchone(self):
        if "to_regprocedure" in self._last:
            return {"?column?": self.available} if self.row_kind == "dict" else (self.available,)
        return {"count": self.drift} if self.row_kind == "dict" else (0, self.drift)


def test_the_check_is_skipped_before_the_migration_lands():
    cursor = _Cursor(available=False)
    assert finding_attention.check_and_repair_state(cursor, 1) == 0
    assert len(cursor.executed) == 1


def test_the_check_records_then_repairs_and_returns_the_count(caplog):
    drift = 3
    cursor = _Cursor(drift=drift)
    assert finding_attention.check_and_repair_state(cursor, 1) == drift
    sql = cursor.executed[-1]
    assert "INSERT INTO operations.finding_state_drift" in sql
    assert "operations.refresh_finding_state(" in sql
    assert any("drift" in record.message for record in caplog.records)


def test_dict_cursors_are_read():
    assert finding_attention.check_and_repair_state(_Cursor(row_kind="dict", drift=0), 1) == 0


def test_record_assessment_no_longer_refreshes_anything_itself():
    source = (ROOT / "ingest" / "conditions.py").read_text(encoding="utf-8")
    assert "finding_attention" not in source


def test_only_the_state_functions_write_finding_state():
    allowed_migrations = {"0301_finding_state.py", "0302_finding_state_skip_unchanged.py"}
    offenders = []
    pattern = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+operations\.finding_state\b", re.I)
    for base in ("ingest", "operations/apps", "operations/config", "shared"):
        for path in (ROOT / base).rglob("*.py"):
            if "tests" in path.parts or path.name in allowed_migrations:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path))
    assert not offenders, offenders


def test_the_hourly_check_compares_the_stored_state():
    source = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    assert "finding_attention.check_and_repair_state(cur, 1)" in source
