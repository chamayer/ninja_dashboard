import hashlib
import importlib
import json

import pytest


def _migration():
    return importlib.import_module("apps.core.migrations.0286_software_inventory_policy")


def _active() -> dict:
    return {
        "schema_version": 1,
        "version": "conditions-jobs-health-1",
        "offline_days": 180,
        "freshness_hours": 48,
        "rules": {"identity": {"effect": "gate", "requires": [], "explanation": "x",
                               "participant_kind": "device"}},
        "definitions": [
            {"name": "whitelist_suggestion", "label": "x", "category": "Software & Security",
             "type": "Software approval needed", "lifecycle": "active", "rules": []},
        ],
        "issue_taxonomy": [
            {"key": "data_collection", "label": "Data collection", "types": [
                {"key": "collection_failures", "label": "x", "conditions": ["source_failure"]},
            ]},
            {"key": "software_security", "label": "Software", "types": [
                {"key": "software_approval", "label": "x", "conditions": ["whitelist_suggestion"]},
            ]},
        ],
    }


def test_policy_adds_both_types_once_and_keeps_everything_else():
    migration = _migration()
    active = _active()
    policy = migration.build_policy(active)

    assert policy["version"] == "conditions-software-inventory-1"
    names = [item["name"] for item in policy["definitions"]]
    assert names == ["whitelist_suggestion", "software_inventory_held",
                     "rejected_software_installed"]
    taxonomy = {item["key"]: item for item in policy["issue_taxonomy"]}
    assert "software_inventory_held" in taxonomy["data_collection"]["types"][0]["conditions"]
    assert "rejected_software_installed" in (
        taxonomy["software_security"]["types"][0]["conditions"]
    )
    assert active["version"] == "conditions-jobs-health-1"  # the input is not mutated
    assert migration.build_policy(policy)["definitions"] == policy["definitions"]


def test_digest_matches_what_ingest_verifies():
    migration = _migration()
    policy = migration.build_policy(_active())
    expected = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    assert migration.digest(policy) == expected


def test_a_missing_taxonomy_type_fails_the_migration():
    active = _active()
    active["issue_taxonomy"][1]["types"] = []
    with pytest.raises(RuntimeError, match="software_security/software_approval"):
        _migration().build_policy(active)


def test_every_registered_type_has_a_definition():
    migration = _migration()
    assert {row[0] for row in migration.FINDING_TYPES} == {
        item["name"] for item in migration.DEFINITIONS
    }
    held = next(row for row in migration.FINDING_TYPES if row[0] == "software_inventory_held")
    rejected = next(
        row for row in migration.FINDING_TYPES if row[0] == "rejected_software_installed"
    )
    assert held[2] == "admin" and held[6] is False  # admin, no device exposure
    assert rejected[8] is False  # an approval never silences a rejection


def test_policy_is_created_and_activated_through_the_governed_function():
    source = importlib.util.find_spec(
        "apps.core.migrations.0286_software_inventory_policy"
    ).loader.get_source("apps.core.migrations.0286_software_inventory_policy")
    assert "operations.create_condition_policy_version(%s, %s, %s::jsonb)" in source
    assert "UPDATE operations.condition_policy_versions" not in source


def test_migration_follows_0285():
    assert _migration().Migration.dependencies == [
        ("operations", "0285_software_inventory_devices")
    ]
