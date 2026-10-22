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


def _annotate(candidates, cursor_results, clients=(), aliases=(), all_candidates=None):
    client_qs = mock.Mock(filter=mock.Mock(return_value=list(clients)))
    alias_qs = mock.Mock()
    alias_qs.filter.return_value.select_related.return_value = list(aliases)
    candidate_qs = mock.Mock()
    candidate_qs.filter.return_value.only.return_value = [
        row["candidate"] for row in (all_candidates or candidates)
    ]
    with (
        mock.patch.object(views.transaction, "atomic", return_value=nullcontext()),
        mock.patch.object(views.connection, "cursor", return_value=_Cursor(cursor_results)),
        mock.patch.object(views.Client, "objects", client_qs),
        mock.patch.object(views.ClientNameAlias, "objects", alias_qs),
        mock.patch.object(views.ClientCandidate, "objects", candidate_qs),
    ):
        views._add_candidate_evidence(candidates, {1: "R-U-ON", 2: "Hudu"})
    return candidates


def _row(name, refs):
    candidate = SimpleNamespace(
        display_name=name,
        normalized_name=name.lower().replace(" ", ""),
        source_refs=refs,
    )
    return {"candidate": candidate, "refs": refs}


def test_live_computers_and_owning_client_come_from_current_groups_only():
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
    assert row["likely_client"] == {"id": "c1", "name": "Rize", "count": 2}
    assert row["similar_client"] is None


def test_similar_name_is_only_offered_without_computer_evidence():
    row = _row("Abest", [{"source_id": 1, "external_id": "g9", "external_name": "Abest"}])
    client = SimpleNamespace(id="c9", display_name="Abest Inc")
    _annotate([row], [[], []], clients=[client])

    assert row["reported_count"] == 0
    assert row["record_count"] == 0
    assert row["likely_client"] is None
    assert row["similar_client"] == {"id": "c9", "name": "Abest Inc"}


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
    assert "Likely client" in mapping
    assert "No longer reported" in mapping
