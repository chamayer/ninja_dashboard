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
    for template in (
        "entity_admin_list.html",
        "entity_admin_detail.html",
        "entity_candidates_queue.html",
        "entity_candidate_detail.html",
    ):
        get_template(template)
