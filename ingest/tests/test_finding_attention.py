"""Stored finding attention: one writer, refreshed with every assessment."""

from __future__ import annotations

import re
from pathlib import Path

from ingest import finding_attention

ROOT = Path(__file__).resolve().parents[2]


class _Cursor:
    def __init__(self, available=True, row_kind="tuple"):
        self.available = available
        self.row_kind = row_kind
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        value = self.available
        return {"?column?": value} if self.row_kind == "dict" else (value,)


def setup_function(_):
    finding_attention._available.update(at=0.0, ok=False, warned=False)


def test_refresh_calls_the_function_once_it_exists():
    cursor = _Cursor()
    finding_attention.refresh(cursor, ["f1"])
    assert cursor.executed[-1] == ("SELECT operations.refresh_finding_attention(%s::uuid[])", (["f1"],))


def test_refresh_is_skipped_and_warned_before_the_migration_lands(caplog):
    cursor = _Cursor(available=False)
    finding_attention.refresh(cursor, ["f1"])
    finding_attention.refresh(cursor, ["f2"])
    assert not any("refresh_finding_attention(%s" in sql for sql, _ in cursor.executed)
    assert sum("0297" in record.message for record in caplog.records) == 1


def test_dict_cursors_are_read():
    cursor = _Cursor(row_kind="dict")
    finding_attention.refresh(cursor, ["f1"])
    assert cursor.executed[-1][0].startswith("SELECT operations.refresh_finding_attention")


def test_record_assessment_refreshes_entity_findings_after_the_participants():
    source = (ROOT / "ingest" / "conditions.py").read_text(encoding="utf-8")
    assert source.index("reconcile_condition_participants") < source.index("finding_attention.refresh(")
    assert 'if condition.row_kind == "entity":' in source


def test_only_the_refresh_function_writes_attention():
    # The one writer is operations.refresh_finding_attention (migration 0297).
    pattern = re.compile(r"\b(attention|attention_at)\s*=\s*(?!=)", re.I)
    allowed = {"0297_finding_attention.py"}
    offenders = []
    for base in ("ingest", "operations/apps", "shared"):
        for path in (ROOT / base).rglob("*.py"):
            if "tests" in path.parts or ("migrations" in path.parts and path.name in allowed):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if re.search(r"UPDATE\s+operations\.findings", line, re.I) and pattern.search(line):
                    offenders.append(str(path))
    assert not offenders, offenders
