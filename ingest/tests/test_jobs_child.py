"""The Jobs child: one JSON result line on stdout, redacted logs on stderr."""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from ingest import jobs_child, operator_job_queue

RUN, CLAIM = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture
def child(monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    monkeypatch.setattr(jobs_child.sys, "argv", ["jobs_child", "resolver", RUN, CLAIM])
    monkeypatch.setattr(jobs_child.db, "init", lambda dsn: None)

    def run(handler):
        monkeypatch.setattr(
            operator_job_queue, "_execute", lambda key, progress: handler()
        )
        return jobs_child.main()

    yield run
    # The child replaced the root handlers (force=True); give pytest its own back.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


def _result(out):
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0])


def test_success_prints_only_the_result_and_logs_to_stderr(child, capsys):
    def handler():
        logging.getLogger("ingest.identity.resolver").info(
            "resolver: 7 roaming agent records"
        )
        return operator_job_queue.JobExecutionResult(
            result={"roaming": {"ran": True, "records": 7}}
        )

    assert child(handler) == 0
    captured = capsys.readouterr()
    assert _result(captured.out) == {
        "ok": True,
        "rows": None,
        "signals": [],
        "result": {"roaming": {"ran": True, "records": 7}},
    }
    assert "resolver: 7 roaming agent records" in captured.err


def test_failure_is_logged_sanitized_reported_and_exits_nonzero(child, capsys):
    def handler():
        raise RuntimeError("source answered 401 for Bearer abc123 token=xyz789")

    assert child(handler) == 1
    captured = capsys.readouterr()
    result = _result(captured.out)
    assert result["ok"] is False
    assert "abc123" not in result["error"] and "xyz789" not in result["error"]
    assert "Job resolver failed" in captured.err
    assert "abc123" not in captured.err and "xyz789" not in captured.err
