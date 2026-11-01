"""The evaluator commits in guarded batches, only between whole findings."""

from __future__ import annotations

from ingest import evaluator


class _Cursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(" ".join(str(sql).split()))


class _Connection:
    def __init__(self):
        self.log: list[str] = []

    def cursor(self):
        return _Cursor(self.log)

    def commit(self):
        self.log.append("COMMIT")


def _batches(monkeypatch, clock):
    monkeypatch.setattr(evaluator.time, "monotonic", lambda: clock[0])
    conn = _Connection()
    batches = evaluator._EvaluationBatches(conn, 1)
    batches.begin()
    conn.log.clear()
    return batches, conn


def test_checkpoint_waits_for_the_time_budget_then_releases_the_guard(monkeypatch):
    clock = [0.0]
    batches, conn = _batches(monkeypatch, clock)
    batches.checkpoint()
    assert conn.log == []

    clock[0] = evaluator._BATCH_SECONDS
    batches.checkpoint()
    unlock = next(i for i, sql in enumerate(conn.log) if "pg_advisory_unlock" in sql)
    lock = next(i for i, sql in enumerate(conn.log) if "pg_advisory_lock(" in sql)
    snapshot = conn.log.index("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert conn.log[0] == "COMMIT"
    # Release, let queued writers in, retake the guard, then take the new snapshot.
    assert unlock < lock < snapshot
    assert conn.log[snapshot - 1] == "COMMIT"
    assert batches.count == 2


def test_no_batch_ends_inside_a_finding(monkeypatch):
    clock = [0.0]
    batches, conn = _batches(monkeypatch, clock)
    token = evaluator._BATCHES.set(batches)
    try:

        @evaluator._batch_unit
        def inner():
            clock[0] += 10
            evaluator._checkpoint()
            return "inner"

        @evaluator._batch_unit
        def outer():
            clock[0] += 10
            return inner()

        assert outer() == "inner"
        assert "COMMIT" not in conn.log
        evaluator._checkpoint()
        assert "COMMIT" in conn.log
    finally:
        evaluator._BATCHES.reset(token)
