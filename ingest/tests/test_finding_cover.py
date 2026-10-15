"""Covered findings: the parent_open signal built from finding_types.covered_by."""

from __future__ import annotations

from ingest import finding_cover
from shared.conditions.contracts import Condition, Participant, Readiness

COVERED = {
    "stale_required_platform": ["device_offline", "device_missing_from_source"],
    "device_offline": ["device_missing_from_source"],
    "reboot_pending": ["device_offline", "device_missing_from_source", "patching_stalled"],
    "patching_stalled": ["device_offline", "device_missing_from_source"],
}
DEVICE = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


class _Cursor:
    def __init__(self, map_rows=None, open_rows=None):
        self.map_rows = map_rows if map_rows is not None else list(COVERED.items())
        self.open_rows = open_rows or []
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append(" ".join(sql.split())[:60])
        self.last = sql

    def fetchall(self):
        return self.map_rows if "covered_by" in self.last and "SELECT name" in self.last else self.open_rows


def _condition(type_name, *participants, row_kind="entity"):
    return Condition(1, row_kind, "f1", type_name, "k", "open", tuple(participants))


def _device(reference=DEVICE, role="affected"):
    return Participant("device", reference, role, 1)


def setup_function(_):
    finding_cover._cache.update(at=0.0, map={})


def test_ancestors_follow_chains():
    assert finding_cover.ancestors("reboot_pending", COVERED) == {
        "device_offline", "device_missing_from_source", "patching_stalled",
    }
    assert finding_cover.ancestors("device_missing_from_source", COVERED) == set()


def test_the_root_most_open_parent_carries_the_count():
    # Offline and "no source reports" are both open: the finding is under the root, not the middle one.
    assert finding_cover.root_open_types(
        "stale_required_platform", {"device_offline", "device_missing_from_source"}, COVERED
    ) == ["device_missing_from_source"]
    # Only offline is open: it is the root.
    assert finding_cover.root_open_types("stale_required_platform", {"device_offline"}, COVERED) == ["device_offline"]
    # Nothing open covers it.
    assert finding_cover.root_open_types("stale_required_platform", set(), COVERED) == []
    # Two independent roots are both named.
    chain = {"x": ["a", "b"], "a": [], "b": []}
    assert finding_cover.root_open_types("x", {"a", "b"}, chain) == ["a", "b"]


def test_a_covered_finding_gets_a_blocked_signal_naming_the_parent_finding():
    device = _device()
    cursor = _Cursor(open_rows=[(DEVICE, "parent-finding-id", "device_offline")])
    (signal,) = finding_cover.cover_signals(cursor, _condition("stale_required_platform", device))
    assert signal.prerequisite == "parent_open"
    assert signal.readiness == Readiness.BLOCKED
    assert signal.reason == "covered_by:device_offline"
    assert signal.blocker_references == ("parent-finding-id",)


def test_chain_parents_resolve_to_the_root_finding():
    cursor = _Cursor(
        open_rows=[(DEVICE, "mid", "device_offline"), (DEVICE, "root", "device_missing_from_source")]
    )
    (signal,) = finding_cover.cover_signals(cursor, _condition("reboot_pending", _device()))
    assert signal.blocker_references == ("root",)
    assert signal.reason == "covered_by:device_missing_from_source"


def test_a_parent_on_another_computer_does_not_cover():
    cursor = _Cursor(open_rows=[(OTHER, "parent", "device_offline")])
    (signal,) = finding_cover.cover_signals(cursor, _condition("stale_required_platform", _device()))
    assert signal.readiness == Readiness.READY and signal.reason == "parent_open:none"


def test_every_participant_gets_a_signal_so_the_engine_never_reads_it_as_unknown():
    context = Participant("client", "33333333-3333-3333-3333-333333333333", "context", 1)
    cursor = _Cursor(open_rows=[(DEVICE, "parent", "device_offline")])
    signals = finding_cover.cover_signals(cursor, _condition("stale_required_platform", _device(), context))
    assert [s.readiness for s in signals] == [Readiness.BLOCKED, Readiness.READY]
    assert {s.participant for s in signals} == {_device(), context}


def test_types_with_no_parents_and_admin_rows_are_ready_without_a_lookup():
    cursor = _Cursor()
    (signal,) = finding_cover.cover_signals(cursor, _condition("device_never_patched", _device()))
    assert signal.readiness == Readiness.READY
    assert not any("FROM operations.findings" in q for q in cursor.queries)
    cursor = _Cursor()
    (signal,) = finding_cover.cover_signals(cursor, _condition("stale_required_platform", _device(), row_kind="admin"))
    assert signal.readiness == Readiness.READY


def test_the_parent_map_is_cached_briefly():
    cursor = _Cursor()
    finding_cover.covered_by_map(cursor)
    finding_cover.covered_by_map(cursor)
    assert len([q for q in cursor.queries if "covered_by" in q]) == 1


def test_record_assessment_adds_the_signals_only_when_the_policy_has_the_rule():
    from pathlib import Path

    source = (Path(finding_cover.__file__).parent / "conditions.py").read_text(encoding="utf-8")
    assert "if finding_cover.RULE in profile.rules:" in source
    assert "signals += finding_cover.cover_signals(cur, condition)" in source
