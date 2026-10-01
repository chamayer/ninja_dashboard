import importlib


def test_relation_api_disambiguates_the_selected_run_array_column():
    migration = importlib.import_module(
        "apps.core.migrations.0234_fix_jobs_activity_relations_api"
    )

    assert migration.Migration.dependencies == [
        ("operations", "0233_jobs_activity_relations_api")
    ]
    assert "AS selected_run(id) WHERE selected_run.id IS NULL" in migration.FORWARD_SQL
    assert "CREATE OR REPLACE FUNCTION operations.jobs_activity_relations_v1" in migration.FORWARD_SQL
