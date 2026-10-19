"""A pending-work Job's schedule runs while work is pending; idle is not disabled."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from ingest import operator_job_queue
from shared.jobs_registry import definition, definitions


def test_source_actions_runs_on_pending_work():
    assert definition("source-actions").capability == "pending_work"


def test_every_pending_work_job_has_its_pending_query():
    pending = {job.key for job in definitions() if job.capability == "pending_work"}
    assert pending == set(operator_job_queue._PENDING_WORK_QUERIES)


@pytest.mark.parametrize(
    ("pending", "expected"),
    [
        (True, (True, "Available")),
        (False, (False, "Waiting for pending work.")),
    ],
)
def test_the_schedule_follows_pending_work(monkeypatch, pending, expected):
    statements = []

    class _Cursor:
        def execute(self, sql, params=()):
            statements.append(sql)

        def fetchone(self):
            return (pending,)

    @contextmanager
    def transaction():
        yield _Cursor()

    monkeypatch.setattr(operator_job_queue.db, "transaction", transaction)
    assert operator_job_queue._schedule_enabled("source-actions") == expected
    assert statements[-1] == operator_job_queue._PENDING_WORK_QUERIES["source-actions"]
