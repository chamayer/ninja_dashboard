"""Name-collision groups become review-only issues keyed by Computers (ADR-0034 section 5a)."""

from __future__ import annotations

import uuid

from ingest.identity import findings

A, B, C = (uuid.UUID(f"00000000-0000-4000-8000-00000000000{n}") for n in (1, 2, 3))
CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self._result = []

    def execute(self, sql, params=()):
        if "to_regclass" in sql:
            self._result = [(True,)]
        elif "computer_name_collisions" in sql:
            self._result = self.rows
        elif "FROM operations.devices" in sql:
            self._result = [(str(A), "vdi-1"), (str(B), "vdi-2"), (str(C), "lab220-34")]
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


def test_a_two_way_collision_is_one_group_and_keys_do_not_depend_on_order():
    rows = [
        (A, CLIENT, "newname", "reporting_os", None, [B]),
        (B, CLIENT, "newname", "reporting_os", None, [A]),
        (C, CLIENT, "ctx-x", "current_label", None, [A]),
    ]
    groups = findings.name_collision_groups(_Cursor(rows), 1, {})
    assert len(groups) == 2
    by_members = {tuple(g[2]): g for g in groups}
    pair = by_members[tuple(sorted([str(A), str(B)]))]
    assert pair[0] == A and pair[1] == CLIENT
    assert [r["device_id"] for r in pair[3]["renames"]] == [str(A), str(B)]
    assert pair[3]["computer_count"] == 2 and "different_machines" not in pair[3]
    reversed_groups = findings.name_collision_groups(
        _Cursor(list(reversed(rows))), 1, {}
    )
    assert sorted(tuple(g[2]) for g in reversed_groups) == sorted(by_members)


def test_no_collisions_means_no_groups():
    assert findings.name_collision_groups(_Cursor([]), 1, {}) == []
