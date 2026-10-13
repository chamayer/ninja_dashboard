from pathlib import Path


def test_user_exposure_uses_selected_last_user_read_model():
    migration = Path(
        "apps/core/migrations/0288_ninja_source_link_numeric_lookup.py"
    ).read_text(encoding="utf-8")
    retirement = Path(
        "apps/core/migrations/0289_retire_ninja_source_link_numeric_lookup.py"
    ).read_text(encoding="utf-8")
    read_model = Path(
        "apps/core/migrations/0290_device_last_user_read_model.py"
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
    assert "v_device_last_user_current" in user_risk
    assert "ninja_links AS MATERIALIZED" not in user_risk
    assert "ninja_device_detail_current_shadow" not in user_risk

    assert "entity_attribute_effective_current" in read_model
    assert "definition.key = 'last_user'" in read_model
    assert "effective.status = 'selected'" in read_model
    assert "device.entity_id = effective.entity_id" in read_model
    assert "operations.current_tenant_id()" in read_model
    assert "security_barrier = true" in read_model
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in read_model
    assert "GRANT SELECT ON operations.v_device_last_user_current TO operations_app" in read_model
