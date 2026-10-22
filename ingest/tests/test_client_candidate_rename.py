"""A source group renamed at its source moves to its new candidate (ADR-0038)."""

from __future__ import annotations

import json

from ingest.identity import client_resolver


class _Cursor:
    """Answers the open-candidate lookup; records every statement."""

    def __init__(self, holders):
        self.holders = holders
        self.statements: list[tuple[str, tuple]] = []
        self._rows: list = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        self._rows = self.holders if "source_refs @>" in sql else []

    def fetchall(self):
        return self._rows


def _ref(source_id, external_id):
    return {"source_id": source_id, "external_id": external_id, "external_name": "Rise NYC"}


def test_emptied_open_candidate_closes_as_renamed_with_history():
    refs = [_ref(2, "77")]
    cur = _Cursor([("old-id", refs)])

    client_resolver._release_renamed_group(cur, "rizenyc", "Rize NYC", 2, "77")

    lookup_sql, lookup_params = cur.statements[0]
    assert "status = 'open'" in lookup_sql
    assert "normalized_name <> %s" in lookup_sql
    assert json.loads(lookup_params[2]) == [{"source_id": 2, "external_id": "77"}]
    close_sql, close_params = cur.statements[1]
    assert "status = 'renamed'" in close_sql
    assert "resolved_by = 'resolver'" in close_sql
    assert json.loads(close_params[0]) == refs
    assert close_params[1] == 'renamed at source to "Rize NYC"'
    assert close_params[2] == "old-id"


def test_open_candidate_with_other_groups_only_loses_the_renamed_group():
    cur = _Cursor([("old-id", [_ref(2, "77"), _ref(1, "g1")])])

    client_resolver._release_renamed_group(cur, "rizenyc", "Rize NYC", 2, "77")

    update_sql, update_params = cur.statements[1]
    assert "status" not in update_sql
    assert json.loads(update_params[0]) == [_ref(1, "g1")]


def test_group_without_source_is_left_alone():
    cur = _Cursor([])

    client_resolver._release_renamed_group(cur, "rizenyc", "Rize NYC", None, "77")

    assert cur.statements == []


def test_candidate_upsert_releases_renamed_group_first():
    cur = _Cursor([])
    cur.fetchone = lambda: None

    client_resolver._upsert_candidate(cur, "rizenyc", "Rize NYC", 2, "77", None)

    assert "source_refs @>" in cur.statements[0][0]
    assert "INSERT INTO operations.client_candidates" in cur.statements[-1][0]
