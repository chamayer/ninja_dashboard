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
                "client_id": record.get("client", client),
                "group_id": record.get("group_id"),
                "roaming": record.get("roaming", False),
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


OWN, OTHER, THIRD = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
NAMES = {str(OWN): "Vedorium", str(OTHER): "Landau Realty", str(THIRD): "City Painting"}


def _conflicts(*computers, accepted=None):
    return findings.client_conflicts({c.id: c for c in computers}, accepted or {}, NAMES)


def test_a_record_filed_under_another_client_raises_one_finding_with_a_destination():
    computer = _computer(
        "ved-01",
        {"serial": "abc123"},
        {"platform": "Hudu", "entity_type": "cmdb.asset", "client": OTHER, "group_id": "42"},
    )
    [(subject, details)] = _conflicts(computer)
    assert subject is computer
    assert details["client"] == "Vedorium"
    assert details["move_to_client_id"] == str(OTHER)
    [row] = details["evidence"]
    assert row["kind"] == "record" and row["platform"] == "Hudu"
    assert row["client"] == "Landau Realty" and row["group_id"] == "42"
    assert row["key"].startswith("record:Hudu|")


def test_a_serial_shared_with_another_clients_computer_raises_on_both():
    mine = _computer("pc-1", {"serial": "abc123"})
    theirs = _computer("pc-7", {"serial": "abc123"}, client=OTHER)
    found = {subject.id: details for subject, details in _conflicts(mine, theirs)}
    assert set(found) == {mine.id, theirs.id}
    assert found[mine.id]["evidence"][0]["key"] == f"serial:{theirs.id}"
    assert found[theirs.id]["evidence"][0]["client"] == "Vedorium"


def test_the_same_name_in_another_client_alone_never_raises_it():
    mine = _computer("dc1", {"serial": "abc123"})
    theirs = _computer("dc1", {"serial": "zzz999"}, client=OTHER)
    assert _conflicts(mine, theirs) == []
    # Beside real evidence it is shown as supporting context.
    filed = _computer(
        "dc1", {"platform": "Hudu", "entity_type": "cmdb.asset", "client": THIRD}
    )
    [(_, details)] = _conflicts(filed, theirs)
    assert [m["client"] for m in details["same_name_elsewhere"]] == ["Landau Realty"]


def test_kept_evidence_stays_out_and_new_evidence_raises_it_again():
    computer = _computer(
        "ved-01", {"platform": "Hudu", "entity_type": "cmdb.asset", "client": OTHER}
    )
    key = findings.client_conflicts({computer.id: computer}, {}, NAMES)[0][1]["evidence"][0]["key"]
    accepted = {str(computer.id): {key}}
    assert _conflicts(computer, accepted=accepted) == []
    computer.records.append({**computer.records[0], "entity_key": "new", "client_id": THIRD})
    [(_, details)] = _conflicts(computer, accepted=accepted)
    assert [row["client"] for row in details["evidence"]] == ["City Painting"]


def test_two_other_clients_have_no_single_destination_and_unmapped_or_roaming_records_are_ignored():
    computer = _computer(
        "pc-2",
        {"platform": "Hudu", "entity_type": "cmdb.asset", "client": OTHER},
        {"platform": "LogMeIn", "entity_type": "agent.remote_access", "client": THIRD},
        {"platform": "SentinelOne", "entity_type": "agent.edr", "client": None},
        {"platform": "ScreenConnect", "entity_type": "agent.remote_access", "client": OTHER,
         "roaming": True},
    )
    [(_, details)] = _conflicts(computer)
    assert details["move_to_client_id"] is None
    assert sorted(row["platform"] for row in details["evidence"]) == ["Hudu", "LogMeIn"]

