from __future__ import annotations

import importlib


def test_claim_projector_queues_only_changed_effective_groups() -> None:
    claim_migration = importlib.import_module(
        "apps.core.migrations.0103_attribute_claim_projection"
    )
    sql = claim_migration.PROJECTOR_SQL

    assert "CREATE TEMP TABLE effective_groups_to_queue" in sql
    assert "JOIN claim_rows_to_change changed" in sql
    assert "INSERT INTO entity_attribute_effective_dirty" in sql
    assert "'claim_delta'" in sql


def test_effective_projector_contract_is_deterministic_and_dirty_keyed() -> None:
    migration = importlib.import_module("apps.core.migrations.0108_attribute_effective_projection")
    sql = migration.PROJECTOR_SQL

    assert "FROM entity_attribute_effective_dirty dirty" in sql
    assert "FOR UPDATE OF dirty SKIP LOCKED" in sql
    assert "ORDER BY claim.authority_tier DESC" in sql
    assert "claim.authority_priority DESC" in sql
    assert "last_observed_at DESC" not in sql
    assert "retain_last_uncontested" in sql
    assert "conflict_unknown" in sql
    assert "all_eligible_union" in sql
    assert "operator_replace" in sql
    assert "operator_modify" in sql


def test_decision_writes_land_in_generic_audit_and_forced_rls() -> None:
    migration = importlib.import_module("apps.core.migrations.0108_attribute_effective_projection")

    assert "INSERT INTO audit_log" in migration.SETUP_SQL
    assert "'entity_attribute_decision'" in migration.SETUP_SQL
    assert migration.SETUP_SQL.count("FORCE ROW LEVEL SECURITY") == 8
    assert migration.SETUP_SQL.count("CREATE POLICY tenant_isolation") == 8
    assert "SET CONSTRAINTS ALL IMMEDIATE" in migration.SETUP_SQL


def test_effective_read_model_redacts_sensitive_values() -> None:
    migration = importlib.import_module("apps.core.migrations.0108_attribute_effective_projection")

    assert "definition.sensitivity IN ('sensitive', 'restricted')" in migration.VIEW_SQL
    assert "THEN '[redacted]'" in migration.VIEW_SQL
    assert "effective.tenant_id = operations.current_tenant_id()" in migration.VIEW_SQL
