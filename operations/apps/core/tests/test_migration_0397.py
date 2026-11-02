"""Migration 0397: Ninja device health is a companion of the device record (PLAN-038).

Behavior was validated on a schema-only clone of production (2026-11-02); these
checks keep the projector edits and the cleanup contract from drifting.
"""

from __future__ import annotations

import importlib

migration = importlib.import_module("apps.core.migrations.0397_source_record_companions")


def test_projector_edits_place_on_the_0103_projector():
    sql = migration._projector_sql()
    assert sql.startswith(
        "CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_claims_from_observations("
    )
    assert "owner_observation.canonical_data AS owner_canonical_data" in sql
    assert "COALESCE(owner.external_id, o.external_id)" in sql


def test_records_without_an_owner_are_unaffected():
    sql = migration._projector_sql()
    # A NULL owner must neither withhold claims nor change the projection hash.
    assert "WHERE NOT COALESCE(mapping.document_kind <> 'raw'" in sql
    assert "CASE WHEN owner.id IS NULL THEN '' ELSE" in sql


def test_companion_links_end_through_the_association_writer():
    cleanup = migration.CLEANUP_SQL
    assert "operations.set_source_association(" in cleanup
    assert "DELETE FROM operations.entity_source_links" not in cleanup
    assert "companion records still have links" in cleanup


def test_ninja_health_is_the_registered_companion_stream():
    schema = migration.SCHEMA_SQL
    assert "'device-health', 'ninja_node_id'" in schema
    assert "CREATE CONSTRAINT TRIGGER check_companion_owner" in schema
    assert "CREATE TRIGGER withdraw_companions_with_owner" in schema
