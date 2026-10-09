import importlib


def test_projection_contract_repairs_do_not_depend_on_missing_trigger_columns():
    migration = importlib.import_module(
        "apps.core.migrations.0273_repair_derived_projection_contracts"
    )
    sql = migration.FORWARD_SQL

    assert "to_jsonb(NEW)->>'status'" in sql
    assert "guard_candidate_resolved_entity_class" in sql
    assert "entity.entity_class_id = NEW.proposed_entity_class_id" in sql
    assert "Awaiting a matching source entity." in sql
