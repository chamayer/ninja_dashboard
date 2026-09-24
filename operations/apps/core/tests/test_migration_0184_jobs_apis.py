"""Static contract checks for the constrained Jobs activation migration."""

import importlib


def test_jobs_activation_replaces_only_inert_guards_with_constrained_apis():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0184_jobs_admission_and_schedule_apis"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0183_jobs_contract_preparation")
    ]
    assert "DROP CONSTRAINT jobs_contract_preparation_only" in sql
    assert "jobs_contract_version_known CHECK (contract_version IN (0, 1))" in sql
    assert "DROP CONSTRAINT jobs_schedule_preparation_only" in sql
    assert "CREATE FUNCTION operations.jobs_request" in sql
    assert "CREATE FUNCTION operations.jobs_claim_due_schedule" in sql
    assert "CREATE FUNCTION operations.jobs_try_schedule_leader" in sql
    assert "CREATE FUNCTION operations.jobs_release_schedule_leader" in sql
    assert "SECURITY DEFINER" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "GRANT SELECT" not in sql
    assert "GRANT INSERT" not in sql
    assert "DROP TABLE" not in sql


def test_jobs_request_api_enforces_tenant_context_snapshot_and_idempotency():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0184_jobs_admission_and_schedule_apis"
    )
    sql = migration.FORWARD_SQL

    assert "v_context_tenant <> p_tenant_id OR p_tenant_id <> 1" in sql
    assert "PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);" in sql
    assert "Jobs definition snapshot is not registered" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "request_identity = p_request_identity" in sql
    assert "ON CONFLICT (tenant_id, job_key) WHERE status IN ('queued', 'running')" in sql
    assert "Conflicting legacy or differently scoped active Job must drain first" in sql
    assert "payload contains a reserved key" in sql
    assert "p_payload IS NULL" in sql
    assert "p_input_revisions IS NULL" in sql


def test_jobs_schedule_api_records_one_due_tick_and_has_limited_grants():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0184_jobs_admission_and_schedule_apis"
    )
    sql = migration.FORWARD_SQL

    assert "FOR UPDATE" in sql
    assert "configuration_revision = v_schedule.configuration_revision" in sql
    assert "UNIQUE" not in sql  # Constraints remain owned by 0183.
    assert "p_due_at IS NULL" in sql
    assert "p_next_due_at IS NULL" in sql
    assert "TO operations_app, ninja_ingest" in sql
    assert "TO ninja_ingest;" in sql
    assert "operations_readonly, metabase_ro" in sql
