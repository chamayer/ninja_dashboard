"""The listing "reporting" window follows the tenant's review period (PLAN-012 item 1)."""

from datetime import UTC, datetime

from ingest import computer_listing

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self) -> None:
        self.params: dict | None = None

    def execute(self, _sql: str, params: dict) -> None:
        self.params = params

    def fetchall(self) -> list:
        return []


def test_window_is_the_review_period_when_given():
    cursor = _Cursor()
    computer_listing.load(cursor, 1, NOW, None, 45)
    assert cursor.params["window"] == "45 days"


def test_window_falls_back_to_thirty_days():
    cursor = _Cursor()
    computer_listing.load(cursor, 1, NOW)
    assert cursor.params["window"] == "30 days"


def test_evaluator_passes_the_review_period():
    from pathlib import Path

    source = (Path(computer_listing.__file__).with_name("evaluator.py")).read_text(encoding="utf-8")
    assert "computer_listing.load(cur, tenant_id, now, device_id, review_days)" in source
