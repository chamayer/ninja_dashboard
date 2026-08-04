from __future__ import annotations

import importlib

from django.template.loader import get_template
from django.urls import reverse


def test_generic_admin_views_are_tenant_scoped_redacted_contracts() -> None:
    migration = importlib.import_module("apps.core.migrations.0116_generic_admin_read_models")
    sql = migration.FORWARD_SQL

    for view in (
        "v_entity_admin_summary",
        "v_entity_source_evidence",
        "v_entity_attribute_conflict_admin",
        "v_entity_relationship_admin",
        "v_entity_candidate_admin",
        "v_source_instance_entity_counts",
        "v_source_instance_health",
    ):
        assert f"CREATE OR REPLACE VIEW operations.{view}" in sql
        assert f"ALTER VIEW operations.{view} OWNER TO operations_view_owner" in sql
    assert sql.count("WITH (security_barrier = true)") == 7
    assert "CREATE ROLE operations_view_owner NOLOGIN NOBYPASSRLS" in sql
    assert "REVOKE CREATE ON SCHEMA operations FROM operations_view_owner" in sql
    assert "operations.current_tenant_id()" in sql
    assert "TO operations_app, operations_readonly" in sql
    assert "TO operations_app, operations_readonly, metabase_ro" not in sql
    assert "raw_data" not in sql
    assert "canonical_data" not in sql
    assert "source_actor" not in sql


def test_source_health_counts_are_rows_not_fixed_class_columns() -> None:
    migration = importlib.import_module("apps.core.migrations.0116_generic_admin_read_models")
    sql = migration.FORWARD_SQL

    assert "observation.entity_type" in sql
    assert "entity_type.entity_class_id AS entity_class" in sql
    assert "v_source_instance_entity_counts" in sql
    assert "device_count" not in sql
    assert "client_count" not in sql


def test_generic_admin_routes_and_templates_are_wired() -> None:
    assert reverse("entity_admin_list") == "/admin/entities/"
    assert reverse("entity_candidates_queue") == "/admin/entity-candidates/"
    entity_id = "00000000-0000-0000-0000-000000000001"
    evidence_id = "00000000-0000-0000-0000-000000000002"
    assert (
        reverse("entity_observation_reveal", args=(entity_id, evidence_id))
        == f"/admin/entities/{entity_id}/observations/{evidence_id}/reveal/"
    )
    assert (
        reverse("entity_attribute_reveal", args=(entity_id, "claim", evidence_id))
        == f"/admin/entities/{entity_id}/attributes/claim/{evidence_id}/reveal/"
    )
    for template in (
        "entity_admin_list.html",
        "entity_admin_detail.html",
        "entity_candidates_queue.html",
        "entity_candidate_detail.html",
        "entity_restricted_evidence.html",
    ):
        get_template(template)


def test_reveal_contract_is_permission_checked_audited_and_least_privilege() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0117_audited_restricted_evidence_reveal"
    )
    sql = migration.FORWARD_SQL

    assert (
        "view_restricted_evidence" in migration.Migration.operations[0].options["permissions"][-1]
    )
    assert "can_reveal_restricted_evidence" in sql
    assert "app_user.is_active" in sql
    assert "permission.codename = 'view_restricted_evidence'" in sql
    assert sql.count("'restricted_evidence.revealed'") == 2
    assert "'canonical_entity_id', p_entity_id" in sql
    assert "'record_id', p_observation_id" in sql
    assert "'record_id', p_record_id" in sql
    assert "REVOKE SELECT ON operations.entity_observation_current" in sql
    assert "GRANT SELECT (observation_id)" in sql
    assert "FROM operations_app, operations_readonly, metabase_ro" in sql
    assert "TO operations_app;" in sql
    assert "TO operations_app, operations_readonly;" in sql


def test_observation_metadata_view_excludes_payload_columns() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0117_audited_restricted_evidence_reveal"
    )
    view_sql = migration.FORWARD_SQL.split(
        "CREATE OR REPLACE VIEW operations.v_entity_observation_admin_metadata", 1
    )[1].split("ALTER VIEW operations.v_entity_observation_admin_metadata", 1)[0]

    assert "WITH (security_barrier = true)" in view_sql
    assert "operations.current_tenant_id()" in view_sql
    assert "raw_data" not in view_sql
    assert "canonical_data->>'hostname'" in view_sql
    assert "canonical_data->>'platform_group_id'" in view_sql
