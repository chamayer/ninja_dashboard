"""A Computer linked to more than one client is one finding with three actions (ADR-0040)."""

from __future__ import annotations

import importlib
import uuid
from types import SimpleNamespace

from apps.core import identity_actions
from apps.core.finding_actions import (
    COMPUTER_CLIENT_SOURCE_WRONG,
    FINDING_ACTIONS,
    IDENTITY_ACTIONS,
    KEEP_COMPUTER_CLIENT,
    MOVE_COMPUTER_CLIENT,
)
from apps.core.templatetags.human_labels import client_conflict_summary

migration = importlib.import_module("apps.core.migrations.0340_computer_client_conflict")

TYPE = "computer_client_conflict"
OTHER = str(uuid.UUID(int=2))
TWIN = str(uuid.UUID(int=7))


def _finding(*evidence, move_to=OTHER):
    return SimpleNamespace(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        finding_type=SimpleNamespace(name=TYPE),
        finding_details={"move_to_client_id": move_to, "evidence": list(evidence)},
    )


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def test_the_three_actions_are_registered_identity_actions_for_this_type_only():
    actions = [a for a in FINDING_ACTIONS.values() if TYPE in a.finding_types]
    assert {a.key for a in actions} == {
        MOVE_COMPUTER_CLIENT.key,
        KEEP_COMPUTER_CLIENT.key,
        COMPUTER_CLIENT_SOURCE_WRONG.key,
    }
    assert all(a.finding_types == frozenset({TYPE}) and a.requires_reason for a in actions)
    assert {a.key for a in actions} <= IDENTITY_ACTIONS


def test_move_needs_exactly_one_other_client():
    single = _finding()
    assert identity_actions._refusal([single], [str(single.id)], MOVE_COMPUTER_CLIENT, "x") == ""
    split = _finding(move_to=None)
    assert "no single destination" in identity_actions._refusal(
        [split], [str(split.id)], MOVE_COMPUTER_CLIENT, "x"
    )
    # Keeping it as it is works whatever the evidence names.
    assert identity_actions._refusal([split], [str(split.id)], KEEP_COMPUTER_CLIENT, "x") == ""


def test_move_runs_the_recorded_move_to_the_named_client():
    finding = _finding(
        {"key": "record:Hudu|1", "kind": "record", "client_id": OTHER, "client": "Landau"}
    )
    cur = _Cursor()
    outcome = identity_actions._apply(cur, finding, MOVE_COMPUTER_CLIENT, "checked", 9)
    [(sql, params)] = cur.calls
    assert "operations.move_computer_to_client" in sql
    assert params == (finding.subject_id, OTHER, "checked", 9)
    assert outcome == "Moved to Landau."


def test_keep_records_every_key_and_settles_a_shared_serial_on_both_computers():
    finding = _finding(
        {"key": "record:Hudu|1", "kind": "record", "client_id": OTHER},
        {"key": f"serial:{TWIN}", "kind": "serial", "client_id": OTHER, "device_id": TWIN},
    )
    cur = _Cursor()
    identity_actions._apply(cur, finding, KEEP_COMPUTER_CLIENT, "intended", 9)
    assert [params for _, params in cur.calls] == [
        (finding.subject_id, ["record:Hudu|1", f"serial:{TWIN}"], "intended", 9),
        (TWIN, [f"serial:{finding.subject_id}"], "intended", 9),
    ]
    assert all("operations.accept_computer_client_conflict" in sql for sql, _ in cur.calls)


def test_source_is_wrong_changes_nothing_and_leaves_the_issue_acknowledged():
    cur = _Cursor()
    outcome = identity_actions._apply(cur, _finding(), COMPUTER_CLIENT_SOURCE_WRONG, "fix Hudu", 9)
    assert cur.calls == [] and "source" in outcome
    assert "status = 'acknowledged'" in identity_actions._ACKNOWLEDGE_SQL


def test_summary_names_the_other_clients_the_sources_and_a_shared_serial():
    details = {
        "evidence": [
            {"kind": "record", "platform": "Hudu", "client": "Landau Realty"},
            {"kind": "serial", "client": "City Painting"},
        ]
    }
    assert client_conflict_summary(details) == (
        "also linked to City Painting, Landau Realty · filed there by Hudu · same serial number"
    )


def test_migration_replaces_cross_client_serial_and_moves_every_live_copy():
    sql = " ".join(migration.FORWARD_SQL.split())
    assert "'client_conflict_accepted', 'device', 'json'" in sql
    assert "WHERE name = 'cross_client_serial')" in sql
    for table in (
        "devices",
        "entities",
        "operating_system_installations",
        "findings",
        "software_installations_current",
        "software_decisions",
        "device_windows_servicing_current",
        "computer_name_collisions",
    ):
        assert f"UPDATE operations.{table} SET client_id = p_client" in sql, table
    # Records keep their source group's client.
    assert "UPDATE operations.entity_observation_current" not in sql
    for function in ("accept_computer_client_conflict", "move_computer_to_client"):
        assert f"GRANT EXECUTE ON FUNCTION operations.{function}(" in sql
        assert f"REVOKE ALL ON FUNCTION operations.{function}(" in sql
    policy = migration.build_policy(
        {"definitions": [{"name": "cross_client_serial", "rules": [], "lifecycle": "active"}]}
    )
    assert policy["version"] == "conditions-registry-10"
    assert {d["name"]: d["lifecycle"] for d in policy["definitions"]} == {
        "cross_client_serial": "historical",
        TYPE: "active",
    }
    assert migration.Migration.dependencies == [
        ("operations", "0339_defer_client_mapping_supersession")
    ]
