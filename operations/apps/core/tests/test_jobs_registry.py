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
    definitions,
    operation_definitions,
    operation_steps,
    schedule_definitions,
    scheduled_definition_keys,
    workflow_edges,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[4]


def test_registry_has_one_catalog_and_schedule_owner_per_definition():
    keys = definition_keys()

    assert len(keys) == 38
    assert {entry["id"] for entry in catalog_entries()} == keys
    assert scheduled_definition_keys() < keys
    assert definition("patches").lane == "collection"
    assert definition("intel-nvd").lane == "intelligence"
    assert definition("software-classify").lane == "software"
    assert definition("notifications-dispatch").lane == "service"
    assert definition("metabase-bootstrap").capability == "metabase_bootstrap"


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
    assert scheduled <= scheduled_definition_keys()
    assert not scheduled
    assert "source-demand" in scheduled_definition_keys()


def test_scheduler_parity_constant_exactly_matches_registered_schedules():
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main)
    assigned = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SCHEDULED_OPERATOR_JOB_KEYS"
            for target in node.targets
        )
    )

    assert isinstance(assigned, ast.Call)
    assert isinstance(assigned.args[0], ast.Set)
    assert {ast.literal_eval(element) for element in assigned.args[0].elts} == scheduled_definition_keys()


def test_every_declared_automatic_schedule_has_one_cadence_contract():
    schedules = schedule_definitions()

    dependent_keys = {successor.successor for item in definitions() for successor in item.successors}
    assert {schedule.job_key for schedule in schedules}.isdisjoint(dependent_keys)
    assert {schedule.schedule_id for schedule in schedules} < {
        schedule_id for item in definitions() for schedule_id in item.schedule_ids
    }
    assert len({schedule.schedule_id for schedule in schedules}) == len(schedules)
    assert all(schedule.cadence_setting for schedule in schedules)


def test_operations_are_meaningful_scheduled_entry_points_with_visible_steps():
    operations = operation_definitions()

    assert {operation.entry_job_key for operation in operations} == scheduled_definition_keys()
    assert all(operation.category in {"Data updates", "Software and security", "Reports", "Maintenance"}
               for operation in operations)
    assert operation_steps("patches") == (
        "patches", "patch-classify", "platform-evaluate", "resolver",
    )


def test_initial_workflow_edges_are_registered_and_acyclic():
    def shape(key, conditions=frozenset({"always"})):
        return tuple(
            (edge.prerequisite, edge.dependent, edge.revision_name, edge.condition)
            for edge in workflow_edges(key, conditions)
        )

    assert shape("patches") == (
        ("patches", "patch-classify", "ninja.patch-snapshot", "always"),
        ("patch-classify", "platform-evaluate", "patch.findings", "always"),
        ("patches", "resolver", "ninja.identity-snapshot", "always"),
        ("resolver", "platform-evaluate", "identity.current", "always"),
    )
    assert shape("software-queue-drain") == (
        ("software-queue-drain", "software-classify-only", "software.inventory-batch", "always"),
    )
    assert shape("agent-compliance") == (
        ("agent-compliance", "resolver", "agent-compliance.observations", "always"),
        ("resolver", "platform-evaluate", "identity.current", "always"),
    )
    assert shape("source-demand") == ()
    assert shape("source-demand", frozenset({"identity_source"})) == (
        ("source-demand", "resolver", "source.identity-observations", "identity_source"),
        ("resolver", "platform-evaluate", "identity.current", "always"),
    )
    assert shape("source-demand", frozenset({"documentation_source"})) == (
        ("source-demand", "cmdb-evaluate", "source.documentation-observations", "documentation_source"),
    )
    assert shape("intel-nvd") == ()
    assert shape("intel-nvd", frozenset({"material_change"})) == (
        ("intel-nvd", "intel-matcher", "intel.cves", "material_change"),
    )

    for item in definitions():
        for successor in item.successors:
            assert successor.scope_mode == "inherit"
            assert successor.coalescing == "definition_scope"
            assert successor.failure_rule == "block"


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


def test_definition_registration_happens_after_database_initialization():
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")

    assert main.index("db.init(settings.postgres_dsn)") < main.index(
        "operator_job_queue.register_definition_snapshots()"
    )


def test_registered_http_jobs_use_governed_admission_before_legacy_routes():
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")

    assert "_HTTP_JOB_PATHS" in main
    assert "operator_job_queue.request_system_job(governed_job, self.path)" in main
    assert "SELECT {request_api}" in queue
    assert '"/bootstrap-metabase": "metabase-bootstrap"' in main
    assert "threading.Thread(target=bootstrap_metabase" not in main


def test_capability_labels_do_not_make_unreviewed_execution_safe():
    enabled, label = capability_state("agent-compliance", {"legacy_agent_compliance": False})
    assert not enabled
    assert label == "Disabled — legacy bridge is not enabled."
    assert definition("agent-compliance").retry_policy == "manual_only_unreviewed"
    assert not definition("agent-compliance").kill_safe


def test_registry_exposes_the_approved_conservative_resource_policy():
    assert INITIAL_EXECUTION_CAPACITY == 2
    assert dict(INITIAL_LANE_CAPACITIES) == {
        "collection": 2,
        "evaluation": 2,
        "software": 2,
        "intelligence": 2,
        "service": 2,
    }
    assert definition("patches").resource_keys == ("tenant:{tenant_id}:ninja-source",)
    assert definition("agent-observations").resource_keys == ("tenant:{tenant_id}:agent-sources",)
    assert definition("patch-classify").resource_keys == ("tenant:{tenant_id}:patch-state",)
    assert "global:intel-cve-corpus" in definition("intel-nvd").resource_keys
    assert "global:software-catalog" in definition("software-classify").resource_keys
    assert definition("software-classify-only").supersession_rank == 1
    assert definition("software-classify-full").supersession_rank == 2
    assert definition("software-classify").supersession_rank == 3
    assert definition("software-classify").supersession_family == "software-classifier"
    assert all(definition(key).resource_keys for key in definition_keys())
    assert all(definition(key).timeout_minutes == 90 for key in definition_keys())
    assert all(definition(key).priority == 50 for key in definition_keys())
    assert all(definition(key).coalescing_scope == "definition_scope" for key in definition_keys())
    assert all(definition(key).concurrency_scope == "resource_keys" for key in definition_keys())
    assert all(definition(key).progress_contract == "stage" for key in definition_keys())
    assert all(definition(key).result_contract == "rows_or_outcome" for key in definition_keys())
    assert all(definition(key).permission in {"administrator", "system"} for key in definition_keys())


def test_registry_snapshot_is_deterministic_and_credential_free():
    snapshot = definition("software-classify").snapshot_metadata()

    assert snapshot["key"] == "software-classify"
    assert snapshot["supersession_family"] == "software-classifier"
    assert definition("software-classify").snapshot_digest() == definition(
        "software-classify"
    ).snapshot_digest()
    assert len(definition("software-classify").snapshot_digest()) == 64
    assert "token" not in json.dumps(snapshot).lower()
    assert snapshot["timeout_minutes"] == 90
    assert snapshot["priority"] == 50
    assert snapshot["coalescing_scope"] == "definition_scope"
    assert snapshot["concurrency_scope"] == "resource_keys"
    assert snapshot["progress_contract"] == "stage"
    assert snapshot["result_contract"] == "rows_or_outcome"
