from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ingest import source_observations


def test_source_collection_continues_then_reports_partial_failure(monkeypatch):
    attempted: list[str] = []
    recorded: list[tuple[str, bool]] = []

    def fetch(source, _observed_at):
        attempted.append(source.source_key)
        if source.source_key == "broken":
            raise RuntimeError("connector failed")
        return [{"external_id": "1"}]

    monkeypatch.setitem(source_observations._FETCHERS, "Test", fetch)
    monkeypatch.setattr(source_observations, "write_observations", lambda *_args: 0)
    monkeypatch.setattr(
        source_observations,
        "_record_source_run",
        lambda source, _started, ok, **_kwargs: recorded.append(
            (source.source_key, ok)
        ),
    )
    sources = [
        SimpleNamespace(
            platform="Test",
            source_key=key,
            source_name=key,
            source_binding_id="binding",
            entity_type="agent.test",
        )
        for key in ("broken", "healthy")
    ]

    with pytest.raises(
        source_observations.SourceObservationFailure, match="1 source collection"
    ) as exc:
        source_observations.run_source_observations(sources, datetime.now(timezone.utc))

    assert exc.value.counts == {"Test": 0}
    assert attempted == ["broken", "healthy"]
    assert recorded == [("broken", False), ("healthy", True)]


def test_empty_collection_is_recorded_as_not_complete(monkeypatch):
    # PLAN-017 F01: an empty fetch opens no snapshot run and withdraws
    # nothing, so it must not be recorded as a healthy zero-row collection.
    recorded: list[tuple[bool, int, str]] = []
    written: list[object] = []

    monkeypatch.setitem(source_observations._FETCHERS, "Test", lambda _s, _t: [])
    monkeypatch.setattr(
        source_observations,
        "write_observations",
        lambda *args: written.append(args) or 0,
    )
    monkeypatch.setattr(
        source_observations,
        "_record_source_run",
        lambda _source, _started, ok, rows, error="": recorded.append(
            (ok, rows, error)
        ),
    )
    source = SimpleNamespace(
        platform="Test",
        source_key="empty",
        source_name="empty",
        source_binding_id="binding",
        entity_type="agent.test",
    )

    with pytest.raises(source_observations.SourceObservationFailure) as exc:
        source_observations.run_source_observations(
            [source], datetime.now(timezone.utc)
        )

    assert exc.value.counts == {}
    assert written == []
    assert len(recorded) == 1
    ok, rows, error = recorded[0]
    assert (ok, rows) == (False, 0)
    assert "no records" in error and "not treated as a complete" in error
