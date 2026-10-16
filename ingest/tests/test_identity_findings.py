"""Identity findings (ADR-0032): two machines on one Computer, same-name Computers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ingest import normalize
from ingest.identity import findings

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _rejections(monkeypatch):
    monkeypatch.setattr(normalize, "_serial_rejection_cache", frozenset({"to be filled by o.e.m."}))


def _computer(name, *records, client=uuid.UUID(int=1), created=0):
    computer = findings._Computer(uuid.uuid4(), client, name, NOW - timedelta(days=100 - created))
    for record in records:
        computer.records.append(
            {
                "observation_id": uuid.uuid4(),
                "platform": record.get("platform", "Ninja"),
                "entity_type": record.get("entity_type", "agent.rmm"),
                "entity_key": str(uuid.uuid4()),
                "stream": f"{record.get('platform', 'Ninja')}:{record.get('entity_type', 'agent.rmm')}",
                "hostname": record.get("hostname", name),
                "serial": record.get("serial"),
                "vm_uuid": record.get("vm_uuid"),
                "online": record.get("online", False),
                "last_seen_at": NOW - timedelta(hours=record.get("hours_ago", 1)),
            }
        )
    return computer


def test_two_serials_propose_splitting_the_machine_without_the_computer_name():
    computer = _computer(
        "gf-12",
        {"serial": "aaa111", "hostname": "gf-12"},
        {"serial": "aaa111", "hostname": "gf-12", "platform": "SentinelOne", "entity_type": "agent.edr"},
        {"serial": "bbb222", "hostname": "gf-32"},
        {"serial": "bbb222", "hostname": "gf-32", "platform": "SentinelOne", "entity_type": "agent.edr"},
        {"hostname": "gf-32", "platform": "LogMeIn", "entity_type": "agent.remote_access"},
    )
    proposal = findings.two_machines(computer, NOW)
    assert proposal["divided_by"] == "serial"
    kept = [m for m in proposal["machines"] if m["keep"]]
    assert [m["hostnames"] for m in kept] == [["gf-12"]]
    # The serial-less LogMeIn record follows its name to the split machine.
    assert len(proposal["proposed_split_observation_ids"]) == 3


def test_two_names_of_one_source_within_a_day_are_two_machines():
    computer = _computer(
        "del-pc01",
        {"hostname": "del-pc01", "hours_ago": 2},
        {"hostname": "del-lt1", "hours_ago": 5},
    )
    assert findings.two_machines(computer, NOW)["divided_by"] == "hostname"
    renamed = _computer(
        "del-pc01",
        {"hostname": "del-pc01", "hours_ago": 2},
        {"hostname": "old-name", "hours_ago": 24 * 20},
    )
    assert findings.two_machines(renamed, NOW) is None
    same_serial = _computer(
        "del-pc01",
        {"hostname": "del-pc01", "serial": "abc123"},
        {"hostname": "del-pc01-new", "serial": "abc123"},
    )
    assert findings.two_machines(same_serial, NOW) is None


def test_documentation_and_rejected_serials_do_not_divide_a_computer():
    computer = _computer(
        "pc-1",
        {"serial": "abc123"},
        {"serial": "zzz999", "platform": "Hudu", "entity_type": "cmdb.asset"},
    )
    assert findings.two_machines(computer, NOW) is None


def test_name_only_computers_form_one_group_and_linked_or_separated_ones_do_not():
    live = _computer("dc1", {"serial": "abc123", "online": True}, created=1)
    ruon = _computer("DC1", {"platform": "R-U-ON", "entity_type": "agent.monitoring"}, created=2)
    other = _computer("dc1", {"serial": "zzz999"}, created=3)
    groups = findings.duplicate_groups(
        {c.id: c for c in (live, ruon, other)}, separated=set()
    )
    assert len(groups) == 1
    subject, details = groups[0]
    assert subject.id in (live.id, ruon.id, other.id)
    # ruon links to both by name, so the three form one group to review,
    # but live and other (different serials) are never a name-only pair.
    assert not findings._name_only_pair(live, other, set())
    assert details["computer_count"] == 3
    assert details["different_machines"] in (
        [[str(live.id), str(other.id)]],
        [[str(other.id), str(live.id)]],
    )

    separated = {(str(live.id), str(ruon.id)), (str(other.id), str(ruon.id))}
    assert findings.duplicate_groups({c.id: c for c in (live, ruon, other)}, separated) == []


def test_two_computers_each_online_in_one_source_are_not_duplicates():
    a = _computer("vm1", {"online": True})
    b = _computer("vm1", {"online": True})
    assert findings.duplicate_groups({a.id: a, b.id: b}, set()) == []


def test_other_clients_never_group():
    a = _computer("pc-9", {"platform": "LogMeIn", "entity_type": "agent.remote_access"})
    b = _computer("pc-9", {}, client=uuid.UUID(int=2))
    assert findings.duplicate_groups({a.id: a, b.id: b}, set()) == []
