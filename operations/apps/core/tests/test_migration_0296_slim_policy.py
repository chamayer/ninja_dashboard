"""Migration 0296: a policy that holds behavior only, plus the generic parent_open rule."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.conditions.contracts import Condition, Participant, Readiness, Signal
from shared.conditions.engine import assess
from shared.conditions.policy import load_profile, parse_profile

_MIGRATION = importlib.import_module("apps.core.migrations.0296_slim_condition_policy")
_PACKAGED = Path(__file__).resolve().parents[4] / "shared" / "conditions" / "profile.json"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _slim():
    return _MIGRATION.build_policy(json.loads(_PACKAGED.read_text(encoding="utf-8")))


def test_the_slim_policy_is_schema_2_with_no_presentation_and_no_offline_threshold():
    policy = _slim()
    assert policy["schema_version"] == 2 and policy["version"] == "conditions-registry-1"
    for key in ("offline_days", "issue_taxonomy", "issue_categories", "issue_type_aliases"):
        assert key not in policy
    for definition in policy["definitions"]:
        assert set(definition) == {"name", "lifecycle", "rules"}
        assert "parent_open" in definition["rules"]


def test_it_parses_and_keeps_every_definition_and_rule():
    profile = parse_profile(_slim())
    original = load_profile()
    assert set(profile.definitions) == set(original.definitions)
    assert {"identity", "offline", "collection", "parent_open"} <= set(profile.rules)
    assert profile.rules["parent_open"]["effect"] == "suppress_attention"
    assert profile.issue_taxonomy == () and profile.issue_type_aliases == ()
    # Existing rules stay attached.
    assert "identity" in profile.definitions["missing_required_platform"]["rules"]


def test_schema_1_versions_still_load():
    assert load_profile().offline_days == 180


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(offline_days=7),
        lambda p: p.update(issue_taxonomy=[]),
        lambda p: p["definitions"][0].update(label="Anything"),
    ],
)
def test_a_schema_2_policy_refuses_presentation_and_the_offline_threshold(mutate):
    policy = _slim()
    mutate(policy)
    with pytest.raises(ValueError):
        parse_profile(policy)


def test_the_digest_is_the_one_the_loaders_check():
    policy = _slim()
    assert parse_profile(policy).digest == _MIGRATION.digest(policy)


def _condition():
    device = Participant("device", "11111111-1111-1111-1111-111111111111", "affected", 1)
    return Condition(1, "entity", "f1", "reboot_pending", "k", "open", (device,)), device


def _other_signals(profile, device):
    return tuple(
        Signal(rule, device, Readiness.READY, f"{rule}:ok")
        for rule in profile.definitions["reboot_pending"]["rules"]
        if rule != "parent_open"
    )


def test_a_blocked_parent_open_signal_covers_the_finding_without_blocking_evaluation():
    profile = parse_profile(_slim())
    condition, device = _condition()
    covered = assess(
        condition,
        profile,
        (*_other_signals(profile, device), Signal("parent_open", device, Readiness.BLOCKED, "covered_by:device_offline", ("f-parent",))),
        NOW,
        device,
    )
    assert covered.disposition == "suppressed"
    assert covered.may_evaluate and not covered.may_notify and not covered.may_execute
    assert "f-parent" in covered.blockers


def test_a_ready_signal_leaves_the_finding_eligible_and_a_missing_one_holds_it():
    profile = parse_profile(_slim())
    condition, device = _condition()
    ready = assess(
        condition, profile,
        (*_other_signals(profile, device), Signal("parent_open", device, Readiness.READY, "parent_open:none")),
        NOW, device,
    )
    assert ready.disposition == "eligible"
    # Why record_assessment always emits the signal: a missing one reads as unknown.
    missing = assess(condition, profile, _other_signals(profile, device), NOW, device)
    assert missing.disposition == "unknown"


def test_the_function_accepts_both_schemas_and_fills_the_per_type_rows_from_the_registry():
    sql = _MIGRATION.FUNCTION_SQL
    assert "doc_schema NOT IN ('1', '2')" in sql
    assert "COALESCE(item->>'label', ft.display_name)" in sql
    assert "COALESCE(item->>'category', ft.issue_category)" in sql
    assert "ALTER COLUMN offline_days DROP NOT NULL" in sql
    assert "PERFORM operations.activate_condition_policy_version(p_version)" in sql
    assert _MIGRATION.Migration.dependencies == [("operations", "0295_finding_types_registry")]
