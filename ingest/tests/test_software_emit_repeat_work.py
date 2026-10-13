from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from ingest import software_findings


class _Cursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(" ".join(sql.split()))

    def fetchone(self):
        return (uuid.uuid4(),)

    def fetchall(self):
        return []


def _emit(cur, scope: str, emitted: set[str]) -> int:
    ft_id = uuid.uuid4()
    product, version, installation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return software_findings._emit_scoped(
        cur, 1, ft_id, uuid.uuid4(), uuid.uuid4(), "Some Title", "Pub", "low",
        datetime.now(timezone.utc), {}, emitted,
        ({ft_id: scope}, product, version, installation),
    )


@pytest.fixture(autouse=True)
def _stub_run_ready(monkeypatch):
    monkeypatch.setattr(software_findings, "successful_run_available", lambda *a, **k: True)


@pytest.mark.parametrize("scope", ["software_product", "software_version"])
def test_repeat_emit_of_title_scoped_finding_skips_participant_rebuild(monkeypatch, scope):
    calls = []
    monkeypatch.setattr(software_findings, "record_assessment", lambda *a, **k: calls.append(1))
    # Pin the subject so both emits resolve to the same condition key.
    monkeypatch.setattr(
        software_findings, "_subject_for",
        lambda *a, **k: (scope, uuid.UUID(int=7), None, None, None),
    )
    monkeypatch.setattr(software_findings, "_condition_key", lambda *a, **k: "key")
    monkeypatch.setattr(software_findings, "device_identity_signal", lambda *a, **k: None)
    monkeypatch.setattr(software_findings, "offline_readiness", lambda *a, **k: ("online", ""))

    emitted: set[str] = set()
    first_cur, repeat_cur = _Cursor(), _Cursor()
    assert _emit(first_cur, scope, emitted) == 1
    first_assessments = len(calls)
    assert first_assessments > 0

    assert _emit(repeat_cur, scope, emitted) == 0
    assert len(calls) == first_assessments  # repeat adds no assessments
    # Only the finding upsert runs again; no device list or per-device lookups.
    assert len(repeat_cur.statements) == 1
    assert repeat_cur.statements[0].startswith("INSERT INTO operations.findings")
