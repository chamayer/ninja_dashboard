"""Focused shared-registry checks; no Django setup or database required."""

import ast
import json
from pathlib import Path

import pytest
from shared.jobs_registry import (
    INITIAL_EXECUTION_CAPACITY,
    INITIAL_LANE_CAPACITIES,
    RegistryValidationError,
    capability_state,
    catalog_entries,
    definition,
    definition_keys,
    scheduled_definition_keys,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[4]


def test_registry_has_one_catalog_and_schedule_owner_per_definition():
    keys = definition_keys()

    assert len(keys) == 30
    assert {entry["id"] for entry in catalog_entries()} == keys
    assert scheduled_definition_keys() < keys
    assert definition("patches").lane == "collection"
    assert definition("intel-nvd").lane == "intelligence"
    assert definition("software-classify").lane == "software"
    assert definition("notifications-dispatch").lane == "service"


def test_registry_rejects_missing_duplicate_and_unregistered_consumer_keys():
    with pytest.raises(RegistryValidationError, match="executable missing"):
        validate_registry(executable_keys=definition_keys() - {"patches"})
    with pytest.raises(RegistryValidationError, match="catalog has duplicate"):
        validate_registry(catalog_keys=(*definition_keys(), "patches"))
    with pytest.raises(RegistryValidationError, match="scheduled has unregistered"):
        validate_registry(scheduled_keys=(*scheduled_definition_keys(), "not-a-job"))


def test_checked_scheduler_source_matches_registry_schedule_keys():
    inventory = json.loads((ROOT / "shared" / "jobs_inventory.json").read_text(encoding="utf-8"))
    scheduled = {
        ast.literal_eval(record["options"]["args"])[0]
        for record in inventory["evidence"]["schedules"]
        if record["callable"] == "operator_job_queue.enqueue_automatic"
    }
    assert scheduled == scheduled_definition_keys()


def test_checked_dispatcher_source_matches_registry_handler_keys():
    inventory = json.loads((ROOT / "shared" / "jobs_inventory.json").read_text(encoding="utf-8"))
    handlers = {record["key"] for record in inventory["evidence"]["handlers"]}
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    tree = ast.parse(queue)
    assigned = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXECUTABLE_JOB_KEYS"
            for target in node.targets
        )
    )

    assert isinstance(assigned, ast.Call)
    assert isinstance(assigned.args[0], ast.Set)
    executable = {ast.literal_eval(element) for element in assigned.args[0].elts}
    assert handlers == executable == definition_keys()


def test_both_runtime_consumers_validate_the_shared_registry():
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")
    views = (ROOT / "operations" / "apps" / "core" / "views.py").read_text(encoding="utf-8")

    assert "validate_registry(executable_keys=EXECUTABLE_JOB_KEYS)" in queue
    assert "scheduled_keys=SCHEDULED_OPERATOR_JOB_KEYS" in main
    assert "_JOB_CATALOG: list[dict] = list(catalog_entries())" in views
    assert 'validate_registry(catalog_keys=(entry["id"] for entry in _JOB_CATALOG))' in views


def test_capability_labels_do_not_make_unreviewed_execution_safe():
    enabled, label = capability_state("agent-compliance", {"legacy_agent_compliance": False})
    assert not enabled
    assert label == "Disabled — legacy bridge is not enabled."
    assert definition("agent-compliance").retry_policy == "manual_only_unreviewed"
    assert not definition("agent-compliance").kill_safe


def test_registry_exposes_the_approved_conservative_resource_policy():
    assert INITIAL_EXECUTION_CAPACITY == 2
    assert dict(INITIAL_LANE_CAPACITIES) == {
        "collection": 1,
        "evaluation": 1,
        "software": 1,
        "intelligence": 1,
        "service": 1,
    }
    assert definition("patches").resource_keys == ("tenant:{tenant_id}:state",)
    assert "global:intel-cve-corpus" in definition("intel-nvd").resource_keys
    assert "global:software-catalog" in definition("software-classify").resource_keys
    assert definition("software-classify-only").supersession_rank == 1
    assert definition("software-classify-full").supersession_rank == 2
    assert definition("software-classify").supersession_rank == 3
    assert definition("software-classify").supersession_family == "software-classifier"
    assert all(definition(key).resource_keys for key in definition_keys())
