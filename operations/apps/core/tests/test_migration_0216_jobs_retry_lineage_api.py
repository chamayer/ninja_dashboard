"""Static contract checks for Jobs retry lineage."""

import importlib


def test_retry_lineage_is_tenant_definition_and_scope_constrained():
    migration = importlib.import_module("apps.core.migrations.0216_jobs_retry_lineage_api")
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_link_retry_v1" in sql
    assert "fresh.job_key = prior.job_key" in sql
    assert "fresh.definition_digest IS NOT DISTINCT FROM prior.definition_digest" in sql
    assert "fresh.scope_identity IS NOT DISTINCT FROM prior.scope_identity" in sql
    assert "prior.contract_version = 0" in sql
    assert "TO operations_app;" in sql
