from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ingest import source_observations


def test_client_attribution_records_the_independent_lookup_used():
    attribute = source_observations._source_client_attribution
    assert attribute("instance-client", "group", {"group": "group-client"}) == (
        "instance-client", {"basis": "source_instance", "client_id": "instance-client"}
    )
    assert attribute(None, "group", {"group": "group-client"}) == (
        "group-client", {"basis": "source_group", "client_id": "group-client"}
    )
    assert attribute(None, "missing", {}) == (None, {"basis": "unknown", "client_id": None})


def test_source_collection_continues_then_reports_partial_failure(monkeypatch):
    attempted: list[str] = []
    recorded: list[tuple[str, bool]] = []

    def fetch(source, _observed_at):
        attempted.append(source.source_key)
        if source.source_key == "broken":
            raise RuntimeError("connector failed")
        return [{"external_id": "1"}]

    monkeypatch.setitem(source_observations._FETCHERS, "Test", fetch)
    monkeypatch.setattr(
        source_observations, "write_observations", lambda *_args, **_kwargs: 0
    )
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
        lambda *args, **_kwargs: written.append(args) or 0,
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


def test_partial_intake_is_reported_failed_with_committed_row_count(monkeypatch):
    recorded = []
    monkeypatch.setitem(
        source_observations._FETCHERS,
        "Test",
        lambda _source, _observed_at: [{"entity_key": "one"}],
    )
    monkeypatch.setattr(
        source_observations,
        "write_observations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            source_observations.PartialIntakeError(1, 1)
        ),
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
        source_key="partial",
        source_name="partial",
        source_binding_id="binding",
        entity_type="agent.test",
    )

    with pytest.raises(source_observations.SourceObservationFailure):
        source_observations.run_source_observations(
            [source], datetime.now(timezone.utc)
        )

    assert len(recorded) == 1
    assert recorded[0][0:2] == (False, 1)
    assert "snapshot was marked incomplete" in recorded[0][2]


def test_intake_identity_error_requires_stable_record_and_container_keys():
    shared = SimpleNamespace(entity_type="agent.test", is_shared=True)
    assert (
        source_observations._intake_identity_error(
            {"external_namespace": "ninja", "entity_key": ""}, shared
        )
        == "missing stable source-record identity"
    )
    assert (
        source_observations._intake_identity_error(
            {
                "_org_only": True,
                "container_external_namespace": "ninja-group",
                "container_external_id": "group-1",
            },
            shared,
        )
        == "missing stable container identity"
    )
    assert (
        source_observations._intake_identity_error(
            {"external_namespace": "ninja", "entity_key": "device-1"},
            SimpleNamespace(entity_type="agent.test", is_shared=False),
        )
        == "missing stable container identity"
    )
    assert (
        source_observations._intake_identity_error(
            {
                "external_namespace": "ninja",
                "entity_key": "device-1",
                "container_external_namespace": "ninja-group",
                "container_external_id": "group-1",
            },
            SimpleNamespace(entity_type="agent.test", is_shared=False),
        )
        == ""
    )


def _marker(reason: str) -> dict:
    return {source_observations.INCOMPLETE_SNAPSHOT_KEY: reason}


def _test_source(key: str) -> SimpleNamespace:
    return SimpleNamespace(
        platform="Test",
        source_key=key,
        source_name=key,
        source_binding_id="binding",
        entity_type="agent.test",
    )


def test_incomplete_marker_writes_rows_as_an_incomplete_snapshot(monkeypatch):
    # PLAN-017 F08 option A: a fetcher that lost part of its source (the
    # SentinelOne sites list) still writes what it read, but the run must not
    # withdraw anything. The marker never reaches the writer as a data row.
    calls: list[tuple[list, str]] = []
    recorded: list[tuple[bool, int, str]] = []
    monkeypatch.setitem(
        source_observations._FETCHERS,
        "Test",
        lambda _s, _t: [{"entity_key": "one"}, _marker("sites list failed")],
    )
    monkeypatch.setattr(
        source_observations,
        "write_observations",
        lambda _source, rows, _batch, _at, *, incomplete_reason="": calls.append(
            (rows, incomplete_reason)
        ) or len(rows),
    )
    monkeypatch.setattr(
        source_observations,
        "_record_source_run",
        lambda _source, _started, ok, rows, error="": recorded.append(
            (ok, rows, error)
        ),
    )

    counts = source_observations.run_source_observations(
        [_test_source("sites-down")], datetime.now(timezone.utc)
    )

    assert counts == {"Test": 1}
    assert calls == [([{"entity_key": "one"}], "sites list failed")]
    assert recorded == [(True, 1, "sites list failed")]


def test_marker_without_rows_is_an_empty_collection(monkeypatch):
    recorded: list[tuple[bool, int, str]] = []
    monkeypatch.setitem(
        source_observations._FETCHERS, "Test", lambda _s, _t: [_marker("down")]
    )
    monkeypatch.setattr(
        source_observations,
        "write_observations",
        lambda *_a, **_k: pytest.fail("an empty collection must not be written"),
    )
    monkeypatch.setattr(
        source_observations,
        "_record_source_run",
        lambda _source, _started, ok, rows, error="": recorded.append(
            (ok, rows, error)
        ),
    )

    with pytest.raises(source_observations.SourceObservationFailure):
        source_observations.run_source_observations(
            [_test_source("all-down")], datetime.now(timezone.utc)
        )

    assert recorded[0][0:2] == (False, 0)
