from contextlib import contextmanager

import pytest

from ingest.identity import resolver


@pytest.fixture
def harness(monkeypatch):
    events = []
    active = []

    @contextmanager
    def transaction(tenant):
        assert tenant == 1
        assert not active
        active.append(True)
        events.append("begin")
        try:
            yield object()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")
        finally:
            active.pop()

    monkeypatch.setattr(resolver.db, "findings_transaction", transaction)
    monkeypatch.setattr(resolver, "load_identity_value_rejections", lambda _: None)
    monkeypatch.setattr(resolver, "refresh_roaming_records", lambda _: None)
    monkeypatch.setattr(resolver, "load_identity_match_policies", lambda *_: ())
    monkeypatch.setattr(
        resolver.computer_client_ownership,
        "reconcile_cycle",
        lambda _: events.append("ownership") or {},
    )
    monkeypatch.setattr(
        resolver.computer_client_ownership,
        "reconcile_dirty",
        lambda _: events.append("ownership") or {},
    )
    monkeypatch.setattr(
        resolver, "_unassociated_identity_ids", lambda limit=None: list(range(23))
    )
    monkeypatch.setattr(resolver, "merge_proven_splits", lambda _: 0)
    monkeypatch.setattr(resolver, "_sync_device_attributes", lambda _: None)
    monkeypatch.setattr(resolver, "project_merge_candidates", lambda _: {})
    monkeypatch.setattr(resolver.device_cache_projector, "project", lambda **_: {})
    monkeypatch.setattr(resolver, "reconcile_computer_names", lambda: None)
    monkeypatch.setattr(resolver, "run_shadow_naming", lambda: None)
    return events, active


def test_resolution_and_promotion_release_guard_between_batches(harness, monkeypatch):
    events, active = harness
    resolved, promoted = [], []

    def resolve(cur, ids):
        assert active
        events.append("resolve")
        resolved.append(list(ids))
        return len(ids), len(ids)

    def promote(cur, policies, *, observation_ids):
        assert active
        events.append("promote")
        promoted.append(list(observation_ids))
        return 0

    monkeypatch.setattr(resolver, "_resolve_observation_batch", resolve)
    monkeypatch.setattr(resolver, "_promote_unmatched_clusters", promote)
    assert resolver.drain_resolution(23, refresh_current=False) == 23
    assert (
        resolved
        == promoted
        == [list(range(10)), list(range(10, 20)), list(range(20, 23))]
    )
    assert events[0] == "ownership"
    for index, event in enumerate(events):
        if event in ("resolve", "promote"):
            assert events[index - 1] == "begin"
            assert events[index + 1] == "commit"
    assert events.count("ownership") == 2
    assert not active


def test_resolution_failure_rolls_back_current_batch_and_escapes(harness, monkeypatch):
    events, active = harness
    attempts = []

    def resolve(cur, ids):
        attempts.append(list(ids))
        if len(attempts) == 2:
            raise RuntimeError("association failed")
        return len(ids), len(ids)

    monkeypatch.setattr(resolver, "_resolve_observation_batch", resolve)
    with pytest.raises(RuntimeError, match="association failed"):
        resolver.drain_resolution(23, refresh_current=False)
    assert len(attempts) == 2
    assert events[-1] == "rollback"
    assert not active


def test_promotion_failure_is_reported_after_prior_batches_commit(harness, monkeypatch):
    events, active = harness
    attempts = []
    monkeypatch.setattr(resolver, "_resolve_observation_batch", lambda *_: (0, 0))

    def promote(cur, policies, *, observation_ids):
        attempts.append(list(observation_ids))
        if len(attempts) == 2:
            raise RuntimeError("promotion failed")
        return 1

    monkeypatch.setattr(resolver, "_promote_unmatched_clusters", promote)
    with pytest.raises(RuntimeError, match="promotion failed"):
        resolver.drain_resolution(23, refresh_current=False)
    assert len(attempts) == 2
    assert events[-1] == "rollback"
    assert not active


def test_batch_uses_fresh_selected_rows_and_names_before_commit(monkeypatch):
    import uuid
    from datetime import datetime, timezone

    observation, device, client, instance = (uuid.uuid4() for _ in range(4))
    events = []

    class Cursor:
        def execute(self, sql, params):
            assert "device_id IS NULL" in sql and "active = TRUE" in sql
            assert "observation_id = ANY" in sql
            assert params[-1] == [observation]

        def fetchall(self):
            return [
                (
                    observation,
                    "agent.rmm",
                    "record",
                    "Ninja",
                    client,
                    datetime.now(timezone.utc),
                    {"hostname": "fresh-name", "serial_number": "fresh-serial"},
                    instance,
                )
            ]

    monkeypatch.setattr(resolver, "load_identity_match_policies", lambda *_: ())
    monkeypatch.setattr(resolver, "identity_entity_types", lambda _: {"agent.rmm"})
    monkeypatch.setattr(resolver, "_load_finding_type_id", lambda *_: 1)
    monkeypatch.setattr(resolver, "record_name_short", lambda *_: "fresh-name")

    def match(cur, **kwargs):
        assert kwargs["serial"] == "fresh-serial"
        assert kwargs["hostname"] == "fresh-name"
        return device

    monkeypatch.setattr(resolver, "resolve_device_by_policy", match)
    monkeypatch.setattr(
        resolver, "_attach_observation", lambda *_: events.append("attach")
    )
    monkeypatch.setattr(
        resolver, "write_computer_names", lambda cur, ids: events.append(("name", ids))
    )
    assert resolver._resolve_observation_batch(Cursor(), [observation]) == (1, 1)
    assert events == ["attach", ("name", {device})]
