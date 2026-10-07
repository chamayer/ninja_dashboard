import importlib


def test_dispatcher_records_the_resource_that_blocks_promotion():
    migration = importlib.import_module("apps.core.migrations.0261_jobs_wait_reason_truth")
    sql = migration.FORWARD_SQL

    assert "v_wait_category TEXT" in sql
    assert "v_wait_category := 'resource'" in sql
    assert "wait_category = v_wait_category" in sql
    assert "another update to finish with the same data" in sql
