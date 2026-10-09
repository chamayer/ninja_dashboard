"""Focused shared-registry checks; no Django setup or database required."""

import ast
import json
from pathlib import Path

import pytest
from shared.jobs_registry import (
    EMERGENCY_CHILD_CAPACITY,
    EXECUTION_POOL_POLICIES,
    READY_WINDOW_CAPACITY,
    RegistryValidationError,
    capability_state,
    catalog_entries,
    definition,
    definition_keys,
    definitions,
    legacy_job_definition_keys,
    operator_job_definitions,
    operator_job_group_definitions,
    operator_job_key_for_execution,
    schedule_definitions,
    scheduled_definition_keys,
    system_service_definition_keys,
    validate_registry,
    workflow_edges,
)

ROOT = Path(__file__).resolve().parents[4]


def test_registry_has_one_catalog_and_schedule_owner_per_definition():
    keys = definition_keys()

    assert len(keys) == 37
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


def test_scheduler_has_no_second_schedule_catalog():
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")
    assert "SCHEDULED_OPERATOR_JOB_KEYS" not in main
    assert "reconcile_schedule_catalog()" in main
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    assert "jobs_disable_retired_tenant_schedules_v1" in queue
    assert "source-demand" not in scheduled_definition_keys()


def test_every_declared_automatic_schedule_has_one_cadence_contract():
    schedules = schedule_definitions()

    dependent_keys = {
        successor.successor for item in definitions() for successor in item.successors
    }
    assert {schedule.job_key for schedule in schedules}.isdisjoint(dependent_keys)
    assert {schedule.schedule_id for schedule in schedules} < {
        schedule_id for item in definitions() for schedule_id in item.schedule_ids
    }
    assert len({schedule.schedule_id for schedule in schedules}) == len(schedules)
    assert all(schedule.cadence_setting for schedule in schedules)


def test_operator_jobs_have_one_visible_boundary_and_services_stay_outside():
    jobs = operator_job_definitions()
    visible_execution_keys = {execution_key for job in jobs for execution_key in job.execution_keys}

    assert "patches" not in {job.key for job in jobs}
    assert operator_job_key_for_execution("patches") is None
    assert operator_job_key_for_execution("source-demand-recovery") is None
    assert operator_job_key_for_execution("software-classify") == "software-classify-only"
    assert next(job for job in jobs if job.key == "cmdb-evaluate").start_description == "After Hudu refresh"
    assert set(system_service_definition_keys()).isdisjoint(visible_execution_keys)
    assert set(legacy_job_definition_keys()).isdisjoint(visible_execution_keys)
    assert (
        visible_execution_keys
        | set(system_service_definition_keys())
        | set(legacy_job_definition_keys())
        == definition_keys()
    )
    group_keys = {key for key, _label in operator_job_group_definitions()}
    assert {job.group_key for job in jobs} <= group_keys
    assert next(job for job in jobs if job.key == "cmdb-evaluate").group_key == "analysis"


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
    assert shape("intel-nvd") == ()
    assert shape("intel-nvd", frozenset({"material_change"})) == (
        ("intel-nvd", "intel-matcher", "intel.cves", "material_change"),
    )
    assert shape("intel-matcher", frozenset({"material_change"})) == (
        ("intel-matcher", "software-classify-only", "software.cve-match", "material_change"),
    )

    assert shape("source-refresh", frozenset({"identity_source"})) == (
        ("source-refresh", "resolver", "source.identity-observations", "identity_source"),
        ("resolver", "platform-evaluate", "identity.current", "always"),
    )
    assert shape("source-refresh", frozenset({"ninja_source"})) == (
        ("source-refresh", "patch-classify", "ninja.patch-snapshot", "ninja_source"),
        ("patch-classify", "platform-evaluate", "patch.findings", "always"),
    )
    assert shape("source-refresh", frozenset({"reference_match_data"})) == (
        (
            "source-refresh",
            "intel-matcher",
            "source.reference-match-data",
            "reference_match_data",
        ),
    )
    assert shape("source-refresh", frozenset({"reference_software_data"})) == (
        (
            "source-refresh",
            "software-classify-only",
            "source.reference-software-data",
            "reference_software_data",
        ),
    )
    assert {
        successor.scope_mode
        for successor in definition("source-refresh").successors
    } == {"tenant"}
    for item in definitions():
        for successor in item.successors:
            assert successor.scope_mode in {"inherit", "tenant"}
            assert successor.coalescing == "definition_scope"
            assert successor.failure_rule == "block"


def test_checked_dispatcher_source_matches_registry_handler_keys():
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    tree = ast.parse(queue)
    jobs = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "jobs"
            for target in node.targets
        )
    )

    assert isinstance(jobs, ast.Dict)
    handler_keys = {ast.literal_eval(key) for key in jobs.keys}
    assert handler_keys | {"software-classify"} == definition_keys()
    assert "EXECUTABLE_JOB_KEYS" not in queue


def test_both_runtime_consumers_validate_the_shared_registry():
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    main = (ROOT / "ingest" / "main.py").read_text(encoding="utf-8")
    views = (ROOT / "operations" / "apps" / "core" / "views.py").read_text(encoding="utf-8")

    assert "validate_registry(executable_keys=definition_keys())" in queue
    assert "SCHEDULED_OPERATOR_JOB_KEYS" not in main
    assert "\n_JOB_CATALOG:" not in views
    assert "validate_registry(catalog_keys=(item.key for item in definitions()))" in views


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
    assert 'request_system_job("metabase-bootstrap", "startup")' not in main
    assert "threading.Thread(target=bootstrap_metabase" not in main


def test_capability_labels_do_not_make_unreviewed_execution_safe():
    enabled, label = capability_state("agent-compliance", {"legacy_agent_compliance": False})
    assert not enabled
    assert label == "Disabled — legacy bridge is not enabled."
    assert definition("agent-compliance").retry_policy == "manual_only_unreviewed"
    assert not definition("agent-compliance").kill_safe


def test_legacy_definitions_cannot_be_automatically_scheduled():
    queue = (ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")

    assert "if job_key in legacy_job_definition_keys():" in queue
    assert 'return False, "Disabled — retired legacy bridge."' in queue
    assert "settings.AGENT_COMPLIANCE_ENABLED" not in queue


def test_registry_exposes_the_approved_pool_and_resource_policy():
    assert READY_WINDOW_CAPACITY == 2
    assert EMERGENCY_CHILD_CAPACITY == 5
    assert dict(EXECUTION_POOL_POLICIES) == {
        "capacity:external-io": {
            "label": "Source connections",
            "capacity": 3,
            "minimum": 1,
            "maximum": 3,
        },
        "capacity:processing": {
            "label": "Data processing",
            "capacity": 2,
            "minimum": 1,
            "maximum": 2,
        },
        "capacity:control": {"label": "Control work", "capacity": 1, "minimum": 1, "maximum": 2},
    }
    assert definition("patches").resource_keys == ("tenant:{tenant_id}:ninja-source",)
    assert definition("source-refresh").resource_keys == (
        "tenant:{tenant_id}:source-binding:{scope_identity}",
    )
    assert definition("agent-observations").resource_keys == ("tenant:{tenant_id}:agent-sources",)
    assert definition("patch-classify").resource_keys == ("tenant:{tenant_id}:patch-state",)
    assert "global:intel-cve-corpus" in definition("intel-nvd").resource_keys
    assert definition("software-classify").resource_keys == (
        "tenant:{tenant_id}:software-state",
        "tenant:{tenant_id}:software-findings",
    )
    assert definition("software-classify-only").supersession_rank == 1
    assert definition("software-classify-full").supersession_rank == 2
    assert definition("software-classify").supersession_rank == 3
    assert definition("software-classify").supersession_family == "software-classifier"
    assert definition("resolver").snapshot_metadata()["recovery_mode"] == "replay_safe"
    assert definition("patch-classify").snapshot_metadata()["recovery_mode"] == "replay_safe"
    assert definition("platform-evaluate").snapshot_metadata()["recovery_mode"] == "replay_safe"
    assert definition("patches").capacity_keys == ()
    assert definition("patch-classify").capacity_keys == ("capacity:processing",)
    assert definition("software-classify").capacity_keys == ("capacity:processing",)
    assert all(
        set(definition(key).capacity_keys) <= set(EXECUTION_POOL_POLICIES)
        for key in definition_keys()
    )
    assert all(definition(key).resource_keys for key in definition_keys())
    assert all(definition(key).timeout_minutes == 90 for key in definition_keys())
    assert all(definition(key).priority == 50 for key in definition_keys())
    assert all(definition(key).coalescing_scope == "definition_scope" for key in definition_keys())
    assert all(definition(key).concurrency_scope == "resource_keys" for key in definition_keys())
    assert all(definition(key).progress_contract == "stage" for key in definition_keys())
    assert all(definition(key).result_contract == "rows_or_outcome" for key in definition_keys())
    assert all(
        definition(key).permission in {"administrator", "system"} for key in definition_keys()
    )


def test_registry_snapshot_is_deterministic_and_credential_free():
    snapshot = definition("software-classify").snapshot_metadata()

    assert snapshot["key"] == "software-classify"
    assert snapshot["supersession_family"] == "software-classifier"
    assert (
        definition("software-classify").snapshot_digest()
        == definition("software-classify").snapshot_digest()
    )
    assert len(definition("software-classify").snapshot_digest()) == 64
    assert "token" not in json.dumps(snapshot).lower()
    assert snapshot["timeout_minutes"] == 90
    assert snapshot["priority"] == 50
    assert snapshot["coalescing_scope"] == "definition_scope"
    assert snapshot["concurrency_scope"] == "resource_keys"
    assert snapshot["progress_contract"] == "stage"
    assert snapshot["result_contract"] == "rows_or_outcome"
