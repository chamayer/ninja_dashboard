from pathlib import Path

from ingest.agent_compliance.config_loader import (
    DEFAULT_MAX_AGE_DAYS,
    get_requirement,
)


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "sql" / "migrations" / "097_agent_compliance_stale_default_180.sql"
_METABASE_BOOTSTRAP = _ROOT / "ingest" / "agent_compliance" / "metabase_bootstrap.py"


def test_missing_requirement_uses_the_180_day_default():
    requirement = get_requirement([], client_id=1, device_scope="server")

    assert DEFAULT_MAX_AGE_DAYS == 180
    assert requirement.max_age_days == 180


def test_setup_dashboard_reads_the_effective_180_day_settings_view():
    migration = _MIGRATION.read_text(encoding="utf-8")
    bootstrap = _METABASE_BOOTSTRAP.read_text(encoding="utf-8")

    assert '"setup_required_platforms"' in bootstrap
    assert "FROM ninja_agent_compliance.v_required_platforms_effective" in bootstrap
    assert "ALTER COLUMN default_max_age_days SET DEFAULT 180" in migration
    assert "WHERE default_max_age_days IS DISTINCT FROM 180" in migration
    assert "WHERE max_age_days IS DISTINCT FROM 180" in migration
    assert "COALESCE(max_age_days, 180) AS max_age_days" in migration
