import uuid
from datetime import datetime, timezone

import pytest

from ingest.observation_runs import begin_run, complete_run


class _Cursor:
    def __init__(self, source_instance_id=None):
        self.source_instance_id = source_instance_id
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        if self.source_instance_id is None:
            return None
        return (self.source_instance_id,)


def test_begin_run_derives_instance_and_dual_writes_run_boundary():
    binding_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    started_at = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    cur = _Cursor(instance_id)

    run_id, resolved_instance_id = begin_run(
        cur, 1, binding_id, "scope", started_at, expected_rows=12
    )

    assert isinstance(run_id, uuid.UUID)
    assert resolved_instance_id == instance_id
    sql, params = cur.calls[0]
    assert "source_instance_id" in sql
    assert "run_started_at" in sql
    assert "is_complete_snapshot" in sql
    assert "RETURNING source_instance_id" in sql
    assert params[-2:] == (binding_id, 1)


def test_begin_run_fails_when_binding_is_outside_tenant():
    cur = _Cursor()

    with pytest.raises(ValueError, match="does not belong"):
        begin_run(cur, 1, uuid.uuid4(), "scope", datetime.now(timezone.utc))


@pytest.mark.parametrize(
    ("failed_rows", "requested_complete", "expected_status", "expected_complete"),
    [
        (0, True, "complete", True),
        (0, False, "complete", False),
        (1, True, "failed", False),
    ],
)
def test_complete_run_records_explicit_snapshot_completeness(
    failed_rows, requested_complete, expected_status, expected_complete
):
    cur = _Cursor()
    run_id = uuid.uuid4()

    complete_run(
        cur,
        run_id,
        written_rows=8,
        failed_rows=failed_rows,
        is_complete_snapshot=requested_complete,
    )

    sql, params = cur.calls[0]
    assert "is_complete_snapshot = %s" in sql
    assert params[0] == expected_status
    assert params[-2:] == (expected_complete, run_id)
