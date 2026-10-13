from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "sql"
    / "migrations"
    / "112_device_software_exposure_read_model.sql"
)


def test_exposure_read_model_keeps_derived_eligibility_and_live_approvals_separate() -> (
    None
):
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE MATERIALIZED VIEW operations.device_software_exposure_current" in sql
    assert "current_installation_evidence" in sql
    assert "JOIN operations.source_instances source_instance" in sql
    assert "mapping.source_id = source_instance.source_id" in sql
    assert "assessment.response->>'may_execute'" in sql
    assert "evidence_fresh_until" in sql
    assert "condition_fresh_until" in sql
    assert "exposure.evidence_fresh_until >= now()" in sql
    assert "exposure.condition_fresh_until >= now()" in sql
    assert "CREATE OR REPLACE VIEW operations.v_device_software_exposure" in sql
    assert "operations.current_tenant_id()" in sql
    assert "decision IN ('approve', 'approve_publisher')" in sql
    assert "device_software_exposure_current_pk" in sql
    assert "device_software_exposure_current_freshness_idx" in sql


def test_exposure_read_model_denies_direct_runtime_access() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "REVOKE ALL ON operations.device_software_exposure_current" in sql
    assert "TO operations_view_owner" in sql
    assert "GRANT SELECT ON operations.v_device_software_exposure" in sql
