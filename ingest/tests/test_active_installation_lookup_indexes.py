from pathlib import Path


def test_active_installation_indexes_match_operations_decision_lookups():
    """Keep both current-installation decision branches indexable.

    These predicates deliberately match the title and publisher joins in the
    read-only Operations exposure and cleanup views.  They must stay partial:
    stale and deleted installations never participate in those projections.
    """
    migration = Path(
        "sql/migrations/116_active_installation_lookup_indexes.sql"
    ).read_text(encoding="utf-8")

    assert "idx_sic_active_tenant_canonical" in migration
    assert "(tenant_id, canonical_name)" in migration
    assert "idx_sic_active_tenant_publisher_lower" in migration
    assert "(tenant_id, LOWER(publisher))" in migration
    assert migration.count("deleted_at IS NULL AND stale_since IS NULL") == 2
    statements = "\n".join(
        line for line in migration.splitlines() if not line.lstrip().startswith("--")
    )
    assert "CREATE INDEX CONCURRENTLY" not in statements
