"""A stop request lets running children finish for a bounded time first."""

from __future__ import annotations

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

from ingest import jobs_worker  # noqa: E402


def _child(exits_after_polls: int | None, *, ownership_lost: bool = False) -> SimpleNamespace:
    polls = {"n": 0}

    def poll():
        polls["n"] += 1
        if exits_after_polls is not None and polls["n"] > exits_after_polls:
            return 0
        return None

    return SimpleNamespace(
        run_id=uuid4(),
        process=SimpleNamespace(poll=poll),
        progress=SimpleNamespace(heartbeat=lambda: None),
        ownership_lost=ownership_lost,
    )


def _patch(monkeypatch, finished):
    monkeypatch.setattr(jobs_worker, "_finish_child", lambda child: finished.append(child.run_id))
    monkeypatch.setattr(jobs_worker.time, "sleep", lambda _s: None)


def test_a_child_that_finishes_within_the_grace_period_is_completed_not_interrupted(monkeypatch):
    finished = []
    _patch(monkeypatch, finished)
    child = _child(exits_after_polls=2)
    children = {child.run_id: child}

    jobs_worker._drain_children(children, grace_seconds=5)

    assert finished == [child.run_id]
    assert children == {}


def test_a_child_still_running_at_the_deadline_is_left_for_fencing(monkeypatch):
    finished = []
    _patch(monkeypatch, finished)
    child = _child(exits_after_polls=None)
    children = {child.run_id: child}

    jobs_worker._drain_children(children, grace_seconds=0.05)

    assert finished == []
    assert list(children) == [child.run_id]


def test_contained_children_do_not_hold_up_shutdown(monkeypatch):
    finished = []
    _patch(monkeypatch, finished)
    child = _child(exits_after_polls=None, ownership_lost=True)
    children = {child.run_id: child}

    jobs_worker._drain_children(children, grace_seconds=60)

    assert list(children) == [child.run_id]


def test_a_failed_finish_stops_draining_so_the_run_is_fenced(monkeypatch):
    def boom(_child):
        raise RuntimeError("cannot record result")

    monkeypatch.setattr(jobs_worker, "_finish_child", boom)
    monkeypatch.setattr(jobs_worker.time, "sleep", lambda _s: None)
    child = _child(exits_after_polls=0)
    children = {child.run_id: child}

    jobs_worker._drain_children(children, grace_seconds=5)

    assert list(children) == [child.run_id]


def test_compose_grace_period_exceeds_the_worker_drain():
    from pathlib import Path

    compose = Path(__file__).resolve().parents[2].joinpath("docker-compose.yml").read_text()
    seconds = int(compose.split("stop_grace_period:")[1].split("s")[0].strip())

    assert seconds > jobs_worker._SHUTDOWN_GRACE_SECONDS
