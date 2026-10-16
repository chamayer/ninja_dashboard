"""The automatic merge planner (ADR-0032): proven splits only, with guards.

Rows mirror PROVEN_SPLIT_SQL: (device, client, created, live, serials,
vm_uuids, online streams, two machines).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ingest.identity.resolver import planned_proven_merges

T0 = datetime(2026, 7, 13, tzinfo=UTC)


class _Cursor:
    """Answers the operator-decision query, then PROVEN_SPLIT_SQL."""

    def __init__(self, rows, separated=()):
        self.results = [list(separated), rows]

    def execute(self, *_args, **_kwargs):
        pass

    def fetchall(self):
        return self.results.pop(0)


def _row(
    device, *, serials=(), vms=(), live=True, online=(), two=False, age=0, client="c1"
):
    return (
        device,
        client,
        T0 + timedelta(days=age),
        live,
        list(serials),
        list(vms),
        list(online),
        two,
    )


def test_same_serial_merges_into_the_oldest_live_computer():
    rows = [
        _row("ninja", serials=["abc123"], online=["Ninja:agent.rmm"]),
        _row("s1", serials=["abc123"], online=["SentinelOne:agent.edr"], age=5),
    ]
    assert planned_proven_merges(_Cursor(rows)) == [("ninja", "s1", "serial", "abc123")]


def test_a_computer_holding_two_machines_is_never_merged():
    rows = [
        _row("two", serials=["abc123"], two=True),
        _row("real", serials=["abc123"], age=3),
    ]
    assert planned_proven_merges(_Cursor(rows)) == []


def test_two_live_installs_of_one_source_are_clones_not_a_split():
    rows = [
        _row("a", serials=["vm-1"], online=["Ninja:agent.rmm"]),
        _row("b", serials=["vm-1"], online=["Ninja:agent.rmm"], age=1),
    ]
    assert planned_proven_merges(_Cursor(rows)) == []


def test_more_than_one_serial_or_conflicting_vm_uuid_is_not_proof():
    rows = [
        _row("a", serials=["abc123", "def456"]),
        _row("b", serials=["abc123"], age=1),
        _row("c", serials=["zzz999"], vms=["u1"]),
        _row("d", serials=["zzz999"], vms=["u2"], age=1),
    ]
    assert planned_proven_merges(_Cursor(rows)) == []


def test_different_clients_and_empty_only_groups_never_merge():
    rows = [
        _row("a", serials=["abc123"], client="c1"),
        _row("b", serials=["abc123"], client="c2"),
        _row("e1", serials=["qqq111"], live=False),
        _row("e2", serials=["qqq111"], live=False, age=1),
    ]
    assert planned_proven_merges(_Cursor(rows)) == []


def test_an_operator_decision_is_never_undone_by_a_merge():
    rows = [
        _row("a", serials=["abc123"]),
        _row("b", serials=["abc123"], age=1),
    ]
    assert planned_proven_merges(_Cursor(rows, separated=[("b", "a")])) == []


def test_an_empty_computer_with_the_same_last_known_serial_joins_the_live_one():
    rows = [
        _row("empty", serials=["abc123"], live=False),
        _row("live", serials=["abc123"], age=9),
    ]
    assert planned_proven_merges(_Cursor(rows)) == [
        ("live", "empty", "serial", "abc123")
    ]
