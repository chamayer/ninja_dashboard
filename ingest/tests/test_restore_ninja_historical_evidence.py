from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest

from ingest import restore_ninja_historical_evidence as restoration


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))


@pytest.mark.parametrize(
    ("apply", "expected_mode"),
    [
        (False, "SET TRANSACTION READ ONLY"),
        (True, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"),
    ],
)
def test_run_sets_safe_transaction_mode(
    monkeypatch: pytest.MonkeyPatch,
    *,
    apply: bool,
    expected_mode: str,
) -> None:
    cursor = _Cursor()

    @contextmanager
    def transaction():
        yield cursor

    expected = object()
    monkeypatch.setattr(restoration.db, "transaction", transaction)
    monkeypatch.setattr(
        restoration,
        "process_range",
        lambda *_args, **_kwargs: expected,
    )

    result = restoration.run(
        start_day=date(2026, 6, 2),
        end_day=date(2026, 6, 3),
        tenant_id=1,
        apply=apply,
    )

    assert result is expected
    assert cursor.executed[0] == (expected_mode, None)
    assert cursor.executed[1] == (
        "SELECT set_config('operations.tenant_id', %s, TRUE)",
        ("1",),
    )


def test_json_result_is_aggregate_only() -> None:
    result = restoration.RestorationResult(
        start_day=date(2026, 6, 2),
        end_day=date(2026, 6, 3),
        legacy_identities=2,
        existing_generic_identities=1,
        missing_generic_identities=1,
        eligible_identities=1,
        blocked_identities=0,
        current_legacy_blockers=0,
        withdrawal_boundary_blockers=0,
        raw_evidence_blockers=0,
        canonical_link_blockers=0,
        history_evidence_blockers=0,
        interval_blockers=0,
        inserted_current_rows=0,
        inserted_history_rows=0,
        apply=False,
    )

    payload = restoration._json_result(result)

    assert payload["blocked_identities"] == 0
    assert payload["start_day"] == "2026-06-02"
    assert payload["end_day"] == "2026-06-03"
    assert all("external" not in key and "device_id" not in key for key in payload)
