from __future__ import annotations

import importlib
from pathlib import Path


def test_relationship_projection_is_dirty_keyed_and_policy_ranked() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0111_relationship_candidate_event_contracts"
    )
    sql = migration.PROJECTOR_SQL

    assert "FROM entity_relationship_dirty dirty" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "authority_tier DESC" in sql
    assert "authority_priority DESC" in sql
    assert "last_observed_at DESC" not in sql
    assert "operator_include" in sql
    assert "operator_exclude" in sql
    assert "source_authority" in sql


def test_relationship_decisions_use_generic_audit_and_forced_rls() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0111_relationship_candidate_event_contracts"
    )

    assert "INSERT INTO audit_log" in migration.TRIGGER_SQL
    assert "'entity_relationship'" in migration.TRIGGER_SQL
    assert migration.RLS_SQL.count("FORCE ROW LEVEL SECURITY") == 7
    assert migration.RLS_SQL.count("CREATE POLICY tenant_isolation") == 7
    assert "GRANT SELECT, INSERT, UPDATE ON operations.source_events" in migration.SECURITY_SQL
    assert "operations.source_events TO operations_app" not in migration.SECURITY_SQL
    assert "source event evidence is immutable" in migration.TRIGGER_SQL


def test_candidate_projection_uses_complete_stable_identity_and_material_reopen() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0111_relationship_candidate_event_contracts"
    )
    sql = migration.PROJECTOR_SQL

    for field in (
        "source_instance_id",
        "external_namespace",
        "parent_external_namespace",
        "parent_external_id",
        "external_id",
    ):
        assert field in sql
    assert "candidate.material_hash IS DISTINCT FROM observation.material_hash" in sql
    assert "'reopen'" in sql
    assert "'attach'" in sql


def test_source_deletion_requires_stable_id_and_never_parses_message() -> None:
    source = Path(__file__).parents[4] / "ingest" / "source_events.py"
    text = source.read_text(encoding="utf-8")

    assert 'payload.get("deviceId")' in text
    assert 'payload.get("message")' not in text
    assert "source event supplied no stable subject identity" in text
    assert "withdrawn != closed" in text
    assert "deleted_at" not in text


def test_relationship_evidence_history_is_change_driven_and_tenant_protected() -> None:
    source = Path(__file__).parents[4] / "ingest" / "relationships.py"
    text = source.read_text(encoding="utf-8")
    security = importlib.import_module(
        "apps.core.migrations.0113_relationship_evidence_history_security"
    )

    assert "material_changed" in text
    assert "effective_to IS NULL" in text
    assert "current/history withdrawal mismatch" in text
    assert "FORCE ROW LEVEL SECURITY" in security.FORWARD_SQL
    assert "TO ninja_ingest" in security.FORWARD_SQL
    assert "TO operations_app" not in security.FORWARD_SQL
