"""Performance diagnostics preserve behavior and omit private input values."""

import logging
from unittest.mock import MagicMock

import pytest

from ingest import evaluator
from ingest.identity import matching


def test_phase_timing_preserves_results_and_omits_inputs(caplog, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(evaluator.time, "monotonic", lambda: clock[0])

    def phase(private_input):
        clock[0] = 12.5
        return (private_input, 7)

    with caplog.at_level(logging.INFO):
        assert evaluator._timed_phase(phase, "private-input") == ("private-input", 7)
    assert "elapsed_seconds=2.500 completed=True" in caplog.text
    assert "private-input" not in caplog.text


def test_phase_failure_is_logged_and_the_same_exception_propagates(caplog):
    failure = ValueError("private-input")

    def phase():
        raise failure

    with caplog.at_level(logging.INFO), pytest.raises(ValueError) as caught:
        evaluator._timed_phase(phase)
    assert caught.value is failure
    assert "completed=False" in caplog.text
    assert "private-input" not in caplog.text


def test_history_timing_is_emitted_only_for_cache_misses_without_records(caplog):
    matching._history_cache.clear()
    cur = MagicMock()
    rows = [("private-record",)]
    cur.fetchall.return_value = rows
    try:
        with caplog.at_level(logging.INFO):
            assert matching._history_names(cur, 1, "private-client", ["agent.rmm"]) == rows
            assert matching._history_names(cur, 1, "private-client", ["agent.rmm"]) == rows
        cur.execute.assert_called_once()
        assert caplog.text.count("query=history_names") == 1
        assert "rows=1" in caplog.text
        assert "private-client" not in caplog.text
        assert "private-record" not in caplog.text
    finally:
        matching._history_cache.clear()
