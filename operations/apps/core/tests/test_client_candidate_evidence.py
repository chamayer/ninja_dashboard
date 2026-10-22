import inspect
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.template.loader import get_template

from apps.core import views


class _Cursor:
    """Answers the reported-group query, then the device query."""

    def __init__(self, results):
        self._results = list(results)
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if "SET LOCAL" not in sql:
            self._rows = self._results.pop(0)

    def fetchall(self):
        return self._rows


def _patched(cursor_results, all_candidates):
    candidate_qs = mock.Mock()
    candidate_qs.filter.return_value.only.return_value = list(all_candidates)
    return (
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views.connection, "cursor", return_value=_Cursor(cursor_results)),
        mock.patch.object(views.ClientCandidate, "objects", candidate_qs),
    )


def _annotate(candidates, cursor_results, all_candidates=None):
    atomic, cursor, candidate_qs = _patched(
        cursor_results, [row["candidate"] for row in (all_candidates or candidates)]
    )
    with atomic, cursor, candidate_qs:
        views._add_candidate_evidence(candidates, {1: "R-U-ON", 2: "Hudu"})
    return candidates


def _row(name, refs):
    candidate = SimpleNamespace(
        display_name=name,
        normalized_name=name.lower().replace(" ", ""),
        source_refs=refs,
    )
    return {"candidate": candidate, "refs": refs}


def test_live_records_come_from_current_groups_only():
    row = _row(
        "Rize NYC",
        [
            {"source_id": 1, "external_id": "g1", "external_name": "Rize NYC"},
            {"source_id": 2, "external_id": "77", "external_name": "Rize NYC"},
        ],
    )
    reported = [(1, "g1", False)]
    devices = [
        (1, "g1", "a1", "d1", "c1", "Rize"),
        (1, "g1", "a2", "d2", "c1", "Rize"),
        (1, "g1", "a3", "d3", None, None),
        (1, "g1", "a4", None, None, None),
    ]
    _annotate([row], [reported, devices])

    assert row["reported_count"] == 1
    assert [(g["source"], g["reported"]) for g in row["groups"]] == [
        ("R-U-ON", True),
        ("Hudu", False),
    ]
    assert row["record_count"] == 4
    assert row["computer_count"] == 3


def test_candidate_page_counts_every_owned_computer_in_live_groups():
    row = _row(
        "GF Supplies",
        [
            {"source_id": 2, "external_id": "h1", "external_name": "GF Supplies"},
            {"source_id": 1, "external_id": "gone", "external_name": "GF Supplies"},
        ],
    )
    reported = [(2, "h1", False)]
    records = [(2, "h1", f"a{i}", f"d{i}", "c1", "GF Supplies / Sigo Signs") for i in range(30)]
    records += [(2, "h1", "b1", "x1", "c2", "Domes"), (2, "h1", "b2", None, None, None)]
    atomic, cursor, candidate_qs = _patched([reported, records], [row["candidate"]])
    with atomic, cursor, candidate_qs:
        live, records_by_group = views._candidate_live_groups(row["candidate"])
        overlap, linked = views._candidate_client_overlap(live, records_by_group)

    # The group the source no longer reports adds nothing.
    assert live == [(2, "h1")]

    # Not capped at a sample: all 30 owned computers count.
    assert overlap == [
        {"client_id": "c1", "display_name": "GF Supplies / Sigo Signs", "device_count": 30},
        {"client_id": "c2", "display_name": "Domes", "device_count": 1},
    ]
    assert linked == 31


def test_name_matches_count_names_only_one_client_owns():
    # (row, named records, client, name, records); a NULL client is an unmatched name.
    rows = [(0, 26, "c1", "Freunds Fish", 16), (0, 26, None, None, 10), (0, 26, "c2", "UTA", 1)]
    with (
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views.connection, "cursor", return_value=_Cursor([rows])),
    ):
        matches, named = views._candidate_name_matches([(1, "g1")])
    assert matches[0] == {"client_id": "c1", "display_name": "Freunds Fish", "record_count": 16}
    assert [m["client_id"] for m in matches] == ["c1", "c2"]
    assert named == 26


def test_name_matches_need_live_groups():
    assert views._candidate_name_matches([]) == ([], 0)


def test_name_match_sql_ignores_names_several_clients_share():
    source = inspect.getsource(views._name_matches_by_row)
    assert "HAVING count(DISTINCT device.client_id) = 1" in source
    assert "observation.device_id IS NULL" in source
    assert "device.lifecycle_status <> 'retired'" in source


def test_group_renamed_at_the_source_belongs_to_the_newest_name():
    old = _row(
        "Rise NYC",
        [{"source_id": 2, "external_id": "77", "observed_at": "2026-09-04T10:34:00+00:00"}],
    )
    new = _row(
        "Rize NYC",
        [{"source_id": 2, "external_id": "77", "observed_at": "2026-10-22T10:55:00+00:00"}],
    )
    reported = [(2, "77", False)]
    devices = [(2, "77", "a1", None, None, None)]
    _annotate([old, new], [reported, devices])

    assert old["groups"][0]["state"] == "renamed"
    assert old["groups"][0]["renamed_to"] == "Rize NYC"
    assert old["reported_count"] == 0
    assert old["record_count"] == 0
    assert old["renamed_to"] == ["Rize NYC"]
    assert new["groups"][0]["state"] == "reported"
    assert new["record_count"] == 1
    assert new["computer_count"] == 0


def test_attached_group_is_not_counted_as_unattached_evidence():
    row = _row("CNY", [{"source_id": 1, "external_id": "g2"}])
    _annotate([row], [[(1, "g2", True)], [(1, "g2", "a1", "d1", "c1", "CNY Corp")]])

    assert row["groups"][0]["state"] == "attached"
    assert row["record_count"] == 0
    assert row["attached_count"] == 1


def test_unattached_table_replaces_resolver_pass_count():
    get_template("client_mappings.html")
    get_template("client_candidate_detail.html")
    root = Path(__file__).parents[3]
    mapping = (root / "templates/client_mappings.html").read_text(encoding="utf-8")
    detail = (root / "templates/client_candidate_detail.html").read_text(encoding="utf-8")
    assert "row.candidate.seen_count" not in mapping
    assert "candidate.seen_count" not in detail
    assert "Likely client" not in mapping
    assert "Likely client" in detail
    assert "No longer reported" in mapping
