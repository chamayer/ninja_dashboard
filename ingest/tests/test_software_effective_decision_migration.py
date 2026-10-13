from pathlib import Path

MIGRATION = (
    Path(__file__).parents[2] / "sql" / "migrations" / "113_software_effective_decision.sql"
)
PREVIOUS = (
    Path(__file__).parents[2]
    / "sql"
    / "migrations"
    / "112_device_software_exposure_read_model.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _select_list(sql: str, view: str) -> list[str]:
    body = sql[sql.index(f"CREATE OR REPLACE VIEW {view}") :]
    body = body[body.index("SELECT ") + len("SELECT ") : body.index("\n  FROM ")]
    return [part.strip() for part in body.split(",")]


def test_decision_keys_resolve_every_scope_case_insensitively():
    sql = _sql()
    assert "CREATE OR REPLACE VIEW operations.v_software_decision_keys" in sql
    assert "SELECT DISTINCT ON (tenant_id, match_kind, scope, device_id, client_id, match_key)" in sql
    assert "decided_at DESC" in sql
    assert "lower(" in sql
    for scope in ("'device'", "'client'", "'global'"):
        assert scope in sql


def test_exposure_applies_all_six_precedence_levels_in_order():
    sql = _sql()
    order = (
        "title_device.decision, title_client.decision, title_global.decision,\n"
        "           publisher_device.decision, publisher_client.decision, publisher_global.decision"
    )
    assert order in sql
    for alias in (
        "title_device", "title_client", "title_global",
        "publisher_device", "publisher_client", "publisher_global",
    ):
        assert f"LEFT JOIN operations.v_software_decision_keys {alias}" in sql


def test_approval_hides_only_types_the_registry_marks_suppressible():
    sql = _sql()
    assert "finding_type.suppressed_by_approval" in sql
    assert "IN ('approve', 'approve_publisher')" in sql
    # The previous exact-match, device/client-only filters are gone.
    assert "decision.device_id = exposure.device_id" not in sql


def test_public_view_keeps_its_columns_and_freshness_rules():
    assert _select_list(_sql(), "operations.v_device_software_exposure") == _select_list(
        PREVIOUS.read_text(encoding="utf-8"), "operations.v_device_software_exposure"
    )
    sql = _sql()
    assert "exposure.evidence_fresh_until >= now()" in sql
    assert "exposure.condition_fresh_until >= now()" in sql
    assert "operations.current_tenant_id()" in sql


def test_views_are_read_only_for_runtime_roles():
    sql = _sql()
    for view in ("operations.v_software_decision_keys", "operations.v_device_software_exposure"):
        assert f"ALTER VIEW {view} OWNER TO operations_view_owner" in sql
        assert f"REVOKE ALL ON {view}" in sql
    assert sql.count("REVOKE INSERT, UPDATE, DELETE, TRUNCATE") == 2
