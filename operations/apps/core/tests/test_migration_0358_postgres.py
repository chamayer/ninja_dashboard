"""Migration 0358 retires parity_report and legacy_job_key on an isolated PostgreSQL."""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

MODULE = "apps.core.migrations.0358_drop_parity_report_and_legacy_job_key"

# begin_change and the trigger stand in for 0306's change-history machinery:
# the trigger refuses a source_instances change made without a named action,
# as an enforce_action registry row would.
SCHEMA = """
CREATE SCHEMA operations;
CREATE TABLE operations.parity_report (id bigserial PRIMARY KEY, finding_type text NOT NULL);
INSERT INTO operations.parity_report (finding_type) VALUES ('agent_offline');
CREATE TABLE operations.change_history_registry (table_name text PRIMARY KEY);
INSERT INTO operations.change_history_registry VALUES ('parity_report'), ('source_instances');
CREATE TABLE operations.change_actions (action text NOT NULL, actor_kind text NOT NULL);
CREATE FUNCTION operations.begin_change(
    p_action text, p_reason text, p_evidence jsonb, p_actor_kind text, p_actor_id bigint,
    p_process text, p_process_version text, p_tenant_id bigint, p_explicit boolean
) RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    INSERT INTO operations.change_actions VALUES (p_action, p_actor_kind);
    PERFORM set_config('operations.change_action_id', gen_random_uuid()::text, true);
END
$fn$;
CREATE TABLE operations.source_instances (id int PRIMARY KEY, config jsonb NOT NULL);
INSERT INTO operations.source_instances VALUES
    (1, '{"source_key": "reference.nvd", "legacy_job_key": "intel-nvd"}'),
    (2, '{"source_key": "ninja"}');
CREATE FUNCTION operations.require_action() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF nullif(current_setting('operations.change_action_id', true), '') IS NULL THEN
        RAISE EXCEPTION 'Change to operations.% needs an action', TG_TABLE_NAME;
    END IF;
    RETURN NULL;
END
$fn$;
CREATE TRIGGER record_change AFTER UPDATE ON operations.source_instances
    FOR EACH ROW EXECUTE FUNCTION operations.require_action();
"""


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn) as connection:
            connection.execute(SCHEMA)
            module = importlib.import_module(MODULE)
            connection.execute(module.FORWARD_SQL)
            connection.commit()
            yield connection


def test_parity_report_and_its_registry_row_are_gone(conn):
    assert conn.execute("SELECT to_regclass('operations.parity_report')").fetchone()[0] is None
    rows = conn.execute("SELECT table_name FROM operations.change_history_registry").fetchall()
    assert rows == [("source_instances",)]


def test_legacy_job_key_is_removed_and_other_config_kept(conn):
    rows = conn.execute("SELECT id, config FROM operations.source_instances ORDER BY id").fetchall()
    assert rows == [(1, {"source_key": "reference.nvd"}), (2, {"source_key": "ninja"})]


def test_the_config_change_names_its_action(conn):
    rows = conn.execute("SELECT action, actor_kind FROM operations.change_actions").fetchall()
    assert rows == [("source.retire_legacy_job_key", "migration")]
