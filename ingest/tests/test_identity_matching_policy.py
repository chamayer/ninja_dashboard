"""Pure policy checks for strict, recency-independent association decisions."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ingest.identity import matching
from ingest.identity.matching import IdentityMatchPolicy


CLIENT = uuid.uuid4()


def _policies(*, corroboration=False):
    return (
        IdentityMatchPolicy(
            "serial",
            10,
            True,
            True,
            False,
            frozenset({"vm_uuid"}),
            Decimal("1"),
            corroboration,
        ),
        IdentityMatchPolicy(
            "hostname", 20, True, True, False, frozenset(), Decimal("0.7")
        ),
    )


def _resolve(
    monkeypatch,
    candidate_sets,
    *,
    conflict=False,
    require_corroboration=False,
    corroborated=False,
):
    visited = []

    def candidates(_cur, *, matcher, **_kwargs):
        visited.append(matcher)
        return candidate_sets.get(matcher, [])

    monkeypatch.setattr(matching, "_is_roaming", lambda *_args: False)
    monkeypatch.setattr(matching, "_candidates", candidates)
    monkeypatch.setattr(
        matching, "_independently_corroborated", lambda *_args: corroborated
    )
    monkeypatch.setattr(
        matching,
        "_hard_conflict_reason",
        lambda *_args, **_kwargs: "vm_uuid_conflict" if conflict else None,
    )
    preview = matching._resolve_match(
        None,
        tenant_id=1,
        source_name="Ninja",
        external_id="incoming",
        entity_type="agent.rmm",
        serial="SERIAL123",
        vm_uuid=None,
        hostname="workstation",
        macs=[],
        client_id=CLIENT,
        policies=_policies(corroboration=require_corroboration),
        is_online=None,
        source_instance_id=uuid.uuid4(),
        skip_source_identity=False,
        identity_types=["agent.rmm"],
        excluded_observation_ids=(),
        trace=False,
    )
    return preview, visited


def test_ambiguous_stronger_match_does_not_fall_through_to_weaker_matcher(monkeypatch):
    preview, visited = _resolve(
        monkeypatch,
        {
            "serial": [uuid.uuid4(), uuid.uuid4()],
            "hostname": [uuid.uuid4()],
        },
    )
    assert preview.result is None
    assert visited == ["serial"]


def test_unique_match_is_selected_without_activity_ranking(monkeypatch):
    candidate = uuid.uuid4()
    preview, visited = _resolve(monkeypatch, {"serial": [candidate]})
    assert preview.result.device_id == candidate
    assert visited == ["serial"]


def test_hard_conflict_does_not_fall_through_to_weaker_matcher(monkeypatch):
    preview, visited = _resolve(
        monkeypatch,
        {"serial": [uuid.uuid4()], "hostname": [uuid.uuid4()]},
        conflict=True,
    )
    assert preview.result is None
    assert visited == ["serial"]


def test_serial_match_requires_independent_corroboration(monkeypatch):
    strong = uuid.uuid4()
    preview, visited = _resolve(
        monkeypatch, {"serial": [strong]}, require_corroboration=True
    )
    assert preview.result is None
    assert visited == ["serial", "hostname"]


def test_corroborated_serial_match_can_be_selected(monkeypatch):
    strong = uuid.uuid4()
    preview, visited = _resolve(
        monkeypatch,
        {"serial": [strong]},
        require_corroboration=True,
        corroborated=True,
    )
    assert preview.result.device_id == strong
    assert visited == ["serial"]


def test_independent_support_query_excludes_the_incoming_source_instance():
    source_instance = uuid.uuid4()
    candidate = uuid.uuid4()

    class Cursor:
        sql = ""
        params = None

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchone(self):
            return (True,)

    cur = Cursor()
    assert matching._independently_corroborated(
        cur,
        1,
        candidate,
        source_instance,
        "workstation",
        ["aa:bb:cc:dd:ee:ff"],
        ["agent.rmm"],
    )
    assert "eo.source_instance_id <> %s" in cur.sql
    assert cur.params[2] == source_instance


def test_enabled_strong_match_policy_requires_corroboration():
    class Cursor:
        def execute(self, sql, _params):
            assert "requires_independent_corroboration" in sql

        def fetchall(self):
            return [("serial", 10, True, True, False, ["vm_uuid"], Decimal("1"), True)]

    [policy] = matching.load_identity_match_policies(Cursor(), 1)
    assert policy.requires_independent_corroboration
