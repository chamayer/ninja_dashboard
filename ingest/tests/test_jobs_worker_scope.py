"""The worker preserves a claimed run's scope when it finishes workflow work."""

from __future__ import annotations

import io
import os
from types import SimpleNamespace
from uuid import uuid4

for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest import jobs_worker


def _child(scope_identity: str) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=uuid4(),
        claim_token=uuid4(),
        job_key="source-refresh",
        scope_identity=scope_identity,
        process=SimpleNamespace(stdout=io.StringIO('{"ok": true, "signals": ["identity_source"]}\n'), wait=lambda: 0),
    )


def test_worker_admits_source_successors_with_the_claimed_scope(monkeypatch):
    child = _child("source-binding:3d3e37ba-bbb2-4a9b-9d7a-77ed334abf9f")
    admitted = []
    finished = []
    monkeypatch.setattr(jobs_worker.operator_job_queue, "admit_result_workflow", lambda *args: admitted.append(args))
    monkeypatch.setattr(jobs_worker.operator_job_queue, "_finish_v1", lambda *args, **kwargs: finished.append((args, kwargs)))

    jobs_worker._finish_child(child)

    assert admitted[0][-1] == child.scope_identity
    assert finished[0][0][2] == "completed"


def test_worker_fails_immediately_when_source_successor_admission_is_rejected(monkeypatch):
    child = _child("source-binding:3d3e37ba-bbb2-4a9b-9d7a-77ed334abf9f")
    finished = []
    monkeypatch.setattr(
        jobs_worker.operator_job_queue,
        "admit_result_workflow",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("rejected")),
    )
    monkeypatch.setattr(jobs_worker.operator_job_queue, "_finish_v1", lambda *args, **kwargs: finished.append((args, kwargs)))

    jobs_worker._finish_child(child)

    assert finished[0][0][2] == "failed"
    assert "Required follow-up work could not be scheduled" in finished[0][1]["error"]
