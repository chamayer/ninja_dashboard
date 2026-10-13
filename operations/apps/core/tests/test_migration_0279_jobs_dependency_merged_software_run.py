import importlib


def _migration():
    return importlib.import_module(
        "apps.core.migrations.0279_jobs_dependency_accepts_merged_software_run"
    )


def test_dependency_accepts_a_same_family_run_of_equal_or_higher_rank():
    sql = _migration().FORWARD_SQL

    assert "edge.contract->>'successor' = dependent.job_key" in sql
    assert "dependent_definition.metadata->>'supersession_family' = 'software-classifier'" in sql
    assert "(dependent_definition.metadata->>'supersession_rank')::integer >=" in sql
    assert "successor_definition.definition_key = edge.contract->>'successor'" in sql
    # An unknown successor rank must never widen the match.
    assert "2147483647" in sql


def test_every_other_dependency_check_is_kept():
    migration = _migration()
    sql = migration.FORWARD_SQL
    previous = migration._PREVIOUS.FORWARD_SQL

    for fragment in (
        "v_dependent_scope IS DISTINCT FROM p_scope_identity",
        "edge.contract->>'revision_name' = p_revision_name",
        "edge.contract->>'scope_mode' IN ('inherit', 'tenant')",
        "edge.contract->>'failure_rule' = 'block'",
        "v_prerequisite_scope IS DISTINCT FROM p_scope_identity",
        "conflicts with the existing edge",
        "GRANT EXECUTE ON FUNCTION operations.jobs_add_revision_dependency_v1",
    ):
        assert fragment in sql
    assert sql.count("CREATE OR REPLACE FUNCTION") == 1
    assert len(sql) > len(previous)


def test_migration_follows_the_current_head_and_reverses_to_the_previous_function():
    migration = _migration()
    operation = migration.Migration.operations[0]

    assert migration.Migration.dependencies == [("operations", "0278_register_ruon_agent_source")]
    assert operation.reverse_sql == migration._PREVIOUS.FORWARD_SQL
