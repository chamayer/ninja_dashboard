"""The resolver records why each undecided source group joined its client (ADR-0040)."""

from __future__ import annotations

import uuid

from ingest.identity import client_resolver

PROMPT, OTHER = uuid.UUID(int=1), uuid.UUID(int=2)


class _Cursor:
    def __init__(self, undecided, aliases, function_exists=True):
        self.results = [[(function_exists,)], undecided, aliases]
        self.recorded = []
        self._last = None

    def execute(self, sql, params=None):
        if "record_automatic_client_mapping_v1(%s" in sql:
            self.recorded.append(params)
            self._last = [(True,)]
        else:
            self._last = self.results.pop(0)

    def fetchone(self):
        return self._last[0]

    def fetchall(self):
        return self._last


def test_each_reason_names_how_the_group_joined_its_client():
    by_name, by_alias, by_alias_elsewhere, legacy = (uuid.uuid4() for _ in range(4))
    cur = _Cursor(
        [
            (by_name, PROMPT, "Prompt", "PROMPT"),
            (by_alias, PROMPT, "Prompt", "MDA"),
            (by_alias_elsewhere, PROMPT, "Prompt", "Landau"),
            (legacy, PROMPT, "Prompt", None),
        ],
        [("mda", PROMPT, "MDA", "map candidate 1 → prompt"), ("landau", OTHER, "Landau", "")],
    )
    assert client_resolver._record_automatic_mappings(cur) == 4
    reasons = {link: reason for _tenant, link, reason in cur.recorded}
    assert reasons[by_name] == 'Source name "PROMPT" matches the client name.'
    assert reasons[by_alias] == (
        'Source name "MDA" matches the alias "MDA" (map candidate 1 → prompt).'
    )
    # An alias that points at another client did not put the group here.
    assert reasons[by_alias_elsewhere] == "Attached before mapping decisions were recorded."
    assert reasons[legacy] == "Attached before mapping decisions were recorded."


def test_nothing_is_recorded_before_the_migration_has_run():
    cur = _Cursor([(uuid.uuid4(), PROMPT, "Prompt", "Prompt")], [], function_exists=False)
    assert client_resolver._record_automatic_mappings(cur) == 0
    assert cur.recorded == []
