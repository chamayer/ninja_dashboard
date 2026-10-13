from pathlib import Path


def test_ninja_source_link_index_experiment_is_retired_for_materialized_join():
    migration = Path(
        "apps/core/migrations/0288_ninja_source_link_numeric_lookup.py"
    ).read_text(encoding="utf-8")
    retirement = Path(
        "apps/core/migrations/0289_retire_ninja_source_link_numeric_lookup.py"
    ).read_text(encoding="utf-8")
    view = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert "atomic = False" in migration
    assert "CREATE INDEX CONCURRENTLY" in migration
    assert "idx_entity_source_links_ninja_numeric" in migration
    assert "tenant_id," in migration
    assert "source_instance_id" in migration
    assert "external_id::integer" in migration
    assert "entity_class_id = 'device'" in migration
    assert "external_namespace NOT IN ('asset', 'device-health')" in migration

    start = view.index("def software_user_risk")
    user_risk = view[start : view.index("# Jobs —", start)]
    assert "DROP INDEX CONCURRENTLY IF EXISTS operations.idx_entity_source_links_ninja_numeric" in retirement
    assert "FROM operations.v_device_source_link dl" in user_risk
    assert "ninja_links AS MATERIALIZED" in user_risk
