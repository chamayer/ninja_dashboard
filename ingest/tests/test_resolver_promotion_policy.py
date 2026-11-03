"""Each record in an unmatched hostname cluster gets its own match decision."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ingest.identity import resolver


class _Cursor:
    def execute(self, *_args, **_kwargs):
        pass

    def fetchall(self):
        client_id = uuid.uuid4()
        return [
            (
                client_id,
                uuid.uuid4(),
                "Ninja",
                "agent.rmm",
                "record-one",
                datetime(2026, 10, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 2, tzinfo=timezone.utc),
                {"hostname": "shared-host", "serial_number": "S1"},
                uuid.uuid4(),
            ),
            (
                client_id,
                uuid.uuid4(),
                "SentinelOne",
                "agent.edr",
                "record-two",
                datetime(2026, 10, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 2, tzinfo=timezone.utc),
                {"hostname": "shared-host", "serial_number": "S2"},
                uuid.uuid4(),
            ),
        ]


def test_cluster_peer_cannot_lend_a_match_or_association(monkeypatch):
    client_id = uuid.uuid4()
    existing_device = uuid.uuid4()
    promoted_device = uuid.uuid4()
    observation_ids = [uuid.uuid4(), uuid.uuid4()]
    source_instances = [uuid.uuid4(), uuid.uuid4()]
    rows = [
        (
            client_id,
            source_instances[index],
            platform,
            "agent.rmm",
            key,
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 10, 2, tzinfo=timezone.utc),
            {"hostname": "shared-host", "serial_number": serial},
            observation_ids[index],
        )
        for index, (platform, key, serial) in enumerate(
            (("Ninja", "record-one", "S1"), ("SentinelOne", "record-two", "S2"))
        )
    ]

    class Cursor(_Cursor):
        def fetchall(self):
            return rows

    match_calls = []
    attached = []
    created = []
    monkeypatch.setattr(resolver, "_load_agent_ids", lambda _cur: {})
    monkeypatch.setattr(
        resolver, "identity_entity_types", lambda _cur: {"agent.rmm", "agent.edr"}
    )
    monkeypatch.setattr(resolver, "record_name_short", lambda *_args: "shared-host")
    monkeypatch.setattr(resolver, "_collapse_mac_variants", lambda clusters: clusters)
    monkeypatch.setattr(
        resolver, "_collapse_prefix_variants", lambda clusters: clusters
    )
    monkeypatch.setattr(resolver, "invalidate_client_names", lambda *_args: None)
    monkeypatch.setattr(resolver, "write_computer_names", lambda *_args: None)

    def resolve_match(_cur, **kwargs):
        match_calls.append(kwargs)
        return (
            SimpleMatch(existing_device)
            if kwargs["external_id"] == "record-one"
            else None
        )

    monkeypatch.setattr(
        resolver,
        "resolve_match",
        resolve_match,
    )
    monkeypatch.setattr(
        resolver,
        "_attach_observation",
        lambda _cur, observation_id, device_id: attached.append(
            (observation_id, device_id)
        ),
    )
    monkeypatch.setattr(
        resolver,
        "_create_device_for_group",
        lambda _cur, _agents, _client, _name, entries: created.append(entries[0])
        or promoted_device,
    )

    assert resolver._promote_unmatched_clusters(Cursor(), ()) == 1
    assert [call["external_id"] for call in match_calls] == ["record-one", "record-two"]
    assert [call["source_instance_id"] for call in match_calls] == source_instances
    assert attached == [(observation_ids[0], existing_device)]
    assert created[0][2] == "record-two"
    assert created[0][6] == source_instances[1]
    assert created[0][7] == observation_ids[1]


class SimpleMatch:
    def __init__(self, device_id):
        self.device_id = device_id


def test_unresolved_ownership_defers_promotion(monkeypatch):
    monkeypatch.setattr(resolver, "_load_agent_ids", lambda _cur: {})
    monkeypatch.setattr(resolver, "identity_entity_types", lambda _cur: {"agent.rmm", "agent.edr"})
    monkeypatch.setattr(resolver, "record_name_short", lambda *_args: "shared-host")
    monkeypatch.setattr(resolver, "_collapse_mac_variants", lambda clusters: clusters)
    monkeypatch.setattr(resolver, "_collapse_prefix_variants", lambda clusters: clusters)
    monkeypatch.setattr(resolver, "invalidate_client_names", lambda *_args: None)
    monkeypatch.setattr(resolver, "write_computer_names", lambda *_args: None)
    created = []
    monkeypatch.setattr(resolver, "_create_device_for_group", lambda *args: created.append(args))

    def deferred(*_args, **_kwargs):
        raise resolver.OwnershipMatchDeferred()

    monkeypatch.setattr(resolver, "resolve_match", deferred)
    assert resolver._promote_unmatched_clusters(_Cursor(), ()) == 0
    assert created == []
