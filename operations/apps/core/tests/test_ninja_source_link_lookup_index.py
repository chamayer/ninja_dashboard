from pathlib import Path


def test_ninja_source_link_numeric_index_matches_safe_user_exposure_join():
    migration = Path(
        "apps/core/migrations/0288_ninja_source_link_numeric_lookup.py"
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

    user_risk = view[view.index("def software_user_risk") : view.index("# ─", view.index("def software_user_risk") + 1)]
    assert "JOIN operations.v_device_source_link dl" in user_risk
    assert "ninja_links AS MATERIALIZED" not in user_risk
