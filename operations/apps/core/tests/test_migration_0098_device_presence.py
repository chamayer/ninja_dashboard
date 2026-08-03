from __future__ import annotations

import importlib


def test_health_namespace_is_excluded_from_presence_projection() -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0098_exclude_health_from_device_presence"
    )

    assert migration.FORWARD_SQL.count("AND o.external_namespace <> 'device-health'") == 1
    assert "CREATE MATERIALIZED VIEW operations.device_agent_presence_current" in (
        migration.FORWARD_SQL
    )
    assert "CREATE MATERIALIZED VIEW operations.device_session_current" in (migration.FORWARD_SQL)
    assert "CREATE VIEW operations.v_device" in migration.FORWARD_SQL
    assert "CREATE MATERIALIZED VIEW operations.source_health_current" in (migration.FORWARD_SQL)
