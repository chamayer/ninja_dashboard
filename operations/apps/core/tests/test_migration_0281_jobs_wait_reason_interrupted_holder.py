import importlib


def _migration():
    return importlib.import_module(
        "apps.core.migrations.0281_jobs_wait_reason_names_interrupted_holder"
    )


def test_wait_reason_names_an_interrupted_holder():
    sql = _migration().FORWARD_SQL

    assert "count(*) FILTER (WHERE state = 'contained')" in sql
    assert "INTO v_active_claims, v_contained_claims" in sql
    assert "An interrupted update still holds this data and needs review." in sql
    assert "Waiting for another update to finish with the same data." in sql


def test_promotion_and_capacity_rules_are_unchanged():
    migration = _migration()
    sql = migration.FORWARD_SQL
    previous = migration._PREVIOUS.FORWARD_SQL

    for fragment in (
        "IF v_active_claims >= v_capacity THEN",
        "state IN ('held', 'contained')",
        "v_wait_category := 'resource'",
        "FOR UPDATE SKIP LOCKED LIMIT 1",
        "WHILE v_ready < 2 LOOP",
    ):
        assert fragment in sql
        assert fragment in previous
    assert sql.count("CREATE OR REPLACE FUNCTION") == 1


def test_migration_follows_0280_and_reverses_to_0261():
    migration = _migration()

    assert migration.Migration.dependencies == [
        ("operations", "0280_jobs_local_work_replay_safe_recovery")
    ]
    assert migration.Migration.operations[0].reverse_sql == migration._PREVIOUS.FORWARD_SQL
