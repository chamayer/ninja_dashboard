"""Replay-safe runs a worker restart interrupted are requested again, once (2026-10-23)."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager

from psycopg.errors import RaiseException

from ingest import operator_job_queue

INTERRUPTED = uuid.uuid4()
NEW_RUN = uuid.uuid4()
SCOPE = "source-binding:00000000-0000-0000-0000-000000000001"


class _Cursor:
    def __init__(self, rows, refuse=False):
        self.rows = rows
        self.refuse = refuse
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))
        if self.refuse and "operations.jobs_request(" in sql:
            raise RaiseException("Conflicting queued Job is unavailable")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (NEW_RUN,)


def _replay(monkeypatch, rows, refuse=False):
    cur = _Cursor(rows, refuse)
    admitted = []

    @contextmanager
    def transaction():
        yield cur

    monkeypatch.setattr(operator_job_queue.db, "transaction", transaction)
    monkeypatch.setattr(
        operator_job_queue,
        "_admit_workflow",
        lambda c, key, run, scope: admitted.append((key, run, scope)),
    )
    return operator_job_queue.replay_interrupted_runs(), cur, admitted


def test_an_interrupted_source_refresh_is_requested_again_as_a_linked_recovery(
    monkeypatch,
):
    count, cur, admitted = _replay(
        monkeypatch, [(INTERRUPTED, "source-refresh", SCOPE, {"source": "ninja"})]
    )
    assert count == 1
    request = next(
        params for sql, params in cur.statements if "operations.jobs_request(" in sql
    )
    assert request[1] == "source-refresh" and request[3] == SCOPE
    assert request[4] == hashlib.sha256(f"recovery:{INTERRUPTED}".encode()).hexdigest()
    assert request[5] == "recovery" and request[6] == '{"source": "ninja"}'
    link = next(params for sql, params in cur.statements if "jobs_link_retry_v1" in sql)
    assert link == (1, NEW_RUN, INTERRUPTED)
    assert admitted == [("source-refresh", NEW_RUN, SCOPE)]


def test_only_reviewed_replay_safe_runs_once_and_not_already_covered():
    sql = " ".join(operator_job_queue._INTERRUPTED_REPLAY_SAFE_SQL.split())
    assert "assessment.recovery_mode = 'replay_safe'" in sql
    assert "run.terminal_reason = 'worker_interrupted'" in sql
    assert "run.trigger_kind <> 'recovery'" in sql
    assert "retry.retry_of_run_id = run.id" in sql
    assert "later.requested_at > run.requested_at" in sql


def test_a_refused_request_is_rolled_back_alone_and_unknown_jobs_are_skipped(
    monkeypatch,
):
    count, cur, admitted = _replay(
        monkeypatch,
        [
            (INTERRUPTED, "source-refresh", SCOPE, {}),
            (uuid.uuid4(), "retired-job", "tenant:1", {}),
        ],
        refuse=True,
    )
    assert count == 0 and admitted == []
    assert ("ROLLBACK TO SAVEPOINT replay_run", None) in cur.statements
