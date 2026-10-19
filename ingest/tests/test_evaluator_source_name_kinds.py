"""The admin finding for record names without a name kind (ADR-0034)."""

from __future__ import annotations

from datetime import UTC, datetime

from ingest import evaluator

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


class _Cursor:
    def __init__(self, unclassified):
        self.unclassified = unclassified
        self.statements: list[tuple[str, tuple]] = []
        self._result: list = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if "to_regprocedure" in sql:
            self._result = [(True,)]
        elif "source_name_kind_unclassified(%s)" in sql:
            self._result = list(self.unclassified)
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


def _run(monkeypatch, unclassified):
    upserts = []

    def upsert(cur, tenant, ft, key, severity, now, subject, details, measured=False):
        upserts.append((ft, key, subject, details, measured))

    monkeypatch.setattr(evaluator, "_get_finding_type_id", lambda cur, name: 77)
    monkeypatch.setattr(evaluator, "_upsert_admin_finding", upsert)
    cur = _Cursor(unclassified)
    count = evaluator._evaluate_source_name_kinds(cur, 1, NOW)
    resolve = [
        (sql, params)
        for sql, params in cur.statements
        if "SET status = 'resolved'" in sql
    ]
    return count, upserts, resolve


def test_one_measured_finding_per_source_and_record_type(monkeypatch):
    count, upserts, resolve = _run(monkeypatch, [("NewTool", "agent.thing", 12)])
    assert count == 1
    assert upserts == [
        (
            77,
            "source_name_kind_unclassified:NewTool:agent.thing",
            {"platform": "NewTool", "record_type": "agent.thing"},
            {"platform": "NewTool", "record_type": "agent.thing", "records": 12},
            True,
        )
    ]
    # Findings for keys no longer present resolve, only with a clearing assessment.
    assert len(resolve) == 1
    sql, params = resolve[0]
    assert "may_clear" in sql
    assert params == (NOW, 1, 77, ["source_name_kind_unclassified:NewTool:agent.thing"])


def test_everything_classified_resolves_every_open_finding(monkeypatch):
    count, upserts, resolve = _run(monkeypatch, [])
    assert (count, upserts) == (0, [])
    assert resolve[0][1] == (NOW, 1, 77, [])
