"""Static checks for v1 Jobs resource claims and dependency primitives."""

import importlib


def test_claim_migration_adds_tenant_scoped_limits_claims_and_dependencies():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0185_jobs_claims_and_dependencies"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0184_jobs_admission_and_schedule_apis")
    ]
    assert "CREATE TABLE operations.job_lane_limits" in sql
    assert "CREATE TABLE operations.job_resource_limits" in sql
    assert "CREATE TABLE operations.job_resource_claims" in sql
    assert "CREATE TABLE operations.job_dependencies" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "execution:deployment', 2" in sql
    assert "6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275" in sql
    assert "digest(" not in sql
    assert "('collection', 1" not in sql
    assert "DROP TABLE" not in sql


def test_claim_api_uses_fenced_claims_aging_and_all_or_nothing_resources():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0185_jobs_claims_and_dependencies"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_claim_next_v1" in sql
    assert "CREATE FUNCTION operations.jobs_release_v1_claim" in sql
    assert "claim_token" in sql
    assert "claim_generation" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "EXTRACT(EPOCH FROM (now() - job.requested_at)) / 300" in sql
    assert "state IN ('held', 'contained')" in sql
    assert "RETURN NULL;" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_dependency_api_requires_converted_runs_and_rejects_cycles():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0185_jobs_claims_and_dependencies"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_add_dependency_v1" in sql
    assert "CREATE FUNCTION operations.jobs_release_dependencies_v1" in sql
    assert "contract_version = 1" in sql
    assert "WITH RECURSIVE descendants" in sql
    assert "would create a cycle" in sql
    assert "required_output_revision" in sql
    assert "output_revisions @> jsonb_build_object('revision', p_output_revision)" in sql
    assert "TO ninja_ingest;" in sql
