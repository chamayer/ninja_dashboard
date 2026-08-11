from pathlib import Path

def test_projector_uses_managed_rules_and_one_shared_match_set():
    """Managed rules feed the same write/clear set as legacy rows."""
    projector = Path("ingest/intel/eol_match.py").read_text(encoding="utf-8")

    assert "FROM intel.eol_managed_product_rules m" in projector
    assert "LEFT JOIN catalog.publishers pub" in projector
    assert "m.publisher_pattern = ''" in projector
    assert "UNION ALL" in projector
    assert "INTO TEMP TABLE eol_best" in projector
    assert "bm.eol_product = 'oracle-jdk'" in projector
    assert "regexp_replace(sv.version, '^1\\\\.([0-9]+)\\\\..*$', '\\\\1')" in projector


def test_managed_rule_migration_is_narrow_and_retires_only_the_manual_queue():
    migration = Path("sql/migrations/088_managed_eol_product_rules.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS intel.eol_managed_product_rules" in migration
    assert "('oracle-java', 'java%', 'oracle%'" in migration
    assert "('sun-java', 'java%', 'sun%'" in migration
    assert "('sql-server', 'microsoft sql server 20%'" in migration
    assert "('mysql-server', 'mysql server%'" in migration
    assert "M365" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration
    assert "DROP MATERIALIZED VIEW IF EXISTS operations.v_eol_mapping_candidates" in migration
    assert "DROP TABLE" not in migration
