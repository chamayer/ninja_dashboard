from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from ingest import withdraw_ninja_stale_scope as correction


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
    monkeypatch.setattr(correction.db, "transaction", transaction)
    monkeypatch.setattr(correction, "process", lambda *_args, **_kwargs: expected)

    result = correction.run(
        tenant_id=1,
        apply=apply,
        expected_count=1 if apply else None,
        expected_digest="0" * 64 if apply else None,
    )

    assert result is expected
    assert cursor.executed[0] == (expected_mode, None)
    assert cursor.executed[1] == (
        "SELECT set_config('operations.tenant_id', %s, TRUE)",
        ("1",),
    )


def test_operator_result_is_aggregate_only() -> None:
    result = correction.StaleScopeResult(
        tenant_id=1,
        active_records=2,
        eligible_records=1,
        eligible_identity_digest="0" * 64,
        blocked_records=1,
        shape_blockers=0,
        provenance_blockers=0,
        missing_legacy_device_blockers=0,
        current_legacy_device_blockers=1,
        withdrawal_boundary_blockers=0,
        open_history_blockers=0,
        already_corrected_records=0,
        already_corrected_identity_digest="0" * 64,
        updated_current_rows=0,
        closed_history_rows=0,
        apply=False,
    )

    payload = vars(result)

    assert payload["blocked_records"] == 1
    assert all("external_id" not in key and "device_id" not in key for key in payload)


def test_apply_requires_a_positive_pinned_selection() -> None:
    with pytest.raises(ValueError, match="positive expected_count"):
        correction.run(apply=True, expected_count=0, expected_digest="0" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        correction.run(apply=True, expected_count=1, expected_digest="not-a-digest")
