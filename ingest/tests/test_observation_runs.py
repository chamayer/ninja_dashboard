import uuid
from datetime import datetime, timezone

import pytest

from ingest.observation_runs import (
    begin_run,
    complete_run,
    observed_identity_summary,
    reconcile_complete_run,
)


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
    lock_sql, lock_params = cur.calls[1]
    assert "pg_advisory_xact_lock" in lock_sql
    assert lock_params == ("1", str(instance_id), "scope")


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
    assert params[4] == expected_complete
    assert params[5:7] == (8, None)
    assert params[-1] == run_id


def test_observed_identity_summary_is_deterministic_and_deduplicated():
    instance_id = uuid.uuid4()
    rows = [
        {
            "source_instance_id": instance_id,
            "external_namespace": "device",
            "parent_external_namespace": "",
            "parent_external_id": "",
            "external_id": external_id,
        }
        for external_id in ("b", "a", "a")
    ]

    count, digest = observed_identity_summary(rows)
    reverse_count, reverse_digest = observed_identity_summary(reversed(rows))

    assert count == reverse_count == 2
    assert digest == reverse_digest
    assert len(digest) == 32


def test_complete_run_records_compact_identity_summary():
    cur = _Cursor()
    row = {
        "source_instance_id": uuid.uuid4(),
        "external_namespace": "device",
        "parent_external_namespace": "",
        "parent_external_id": "",
        "external_id": "42",
    }

    complete_run(cur, uuid.uuid4(), 1, identity_rows=[row])

    _sql, params = cur.calls[0]
    assert params[5] == 1
    assert len(params[6]) == 32


class _ReconcileCursor:
    def __init__(self, fetches):
        self.fetches = list(fetches)
        self.calls = []
        self.pending = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if "SELECT tenant_id, source_instance_id" in normalized or (
            "SELECT (SELECT COUNT(*) FROM withdrawn)" in normalized
        ):
            self.pending = self.fetches.pop(0)
        else:
            self.pending = None

    def fetchone(self):
        return self.pending


def test_reconcile_skips_non_authoritative_run():
    cur = _ReconcileCursor([None])

    assert reconcile_complete_run(cur, uuid.uuid4()) == 0
    assert len(cur.calls) == 1


def test_reconcile_uses_stable_scope_and_overlap_boundary():
    instance_id = uuid.uuid4()
    started_at = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    cur = _ReconcileCursor([(1, instance_id, "scope", started_at), (2, 2)])

    assert reconcile_complete_run(cur, uuid.uuid4()) == 2

    reconciliation_sql = cur.calls[-1][0]
    assert "c.source_instance_id = r.source_instance_id" in reconciliation_sql
    assert "c.last_received_at < r.run_started_at" in reconciliation_sql
    assert "closed_by_snapshot_run_id = w.run_id" in reconciliation_sql
    assert "h.active = FALSE" not in reconciliation_sql


def test_reconcile_rolls_back_on_current_history_mismatch():
    cur = _ReconcileCursor(
        [(1, uuid.uuid4(), "scope", datetime.now(timezone.utc)), (2, 1)]
    )

    with pytest.raises(RuntimeError, match="current/history mismatch"):
        reconcile_complete_run(cur, uuid.uuid4())
