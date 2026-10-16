"""Migration 0305 on a real PostgreSQL: false lifecycle transitions go, real ones stay.

The table mirrors production (``operations.audit_log`` column types read from
production 2026-10-16, owned by ``operations_migrate`` with row-level security
forced), and the migration runs as that owner, as it does in deployment.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN;
CREATE SCHEMA operations AUTHORIZATION operations_migrate;
CREATE TABLE operations.tenants (
    id bigint PRIMARY KEY,
    slug varchar(64) NOT NULL,
    display_name varchar(200) NOT NULL,
    brand_config jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE operations.audit_log (
    audit_id uuid PRIMARY KEY,
    actor_kind varchar(16) NOT NULL,
    source varchar(32) NOT NULL,
    action varchar(120) NOT NULL,
    entity_type varchar(80) NOT NULL,
    entity_id uuid NULL,
    before_state jsonb NULL,
    after_state jsonb NULL,
    ip_address inet NULL,
    user_agent text NOT NULL,
    occurred_at timestamptz NOT NULL,
    actor_id bigint NULL,
    tenant_id bigint NOT NULL
);
ALTER TABLE operations.tenants OWNER TO operations_migrate;
ALTER TABLE operations.audit_log OWNER TO operations_migrate;
ALTER TABLE operations.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.audit_log
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
INSERT INTO operations.tenants (id, slug, display_name) VALUES (1, 't1', 'Tenant 1');
"""


def _transition(conn, entity_id, run_id, before, after, evidence_kind):
    after_state = {"lifecycle_status": after, "evidence_kind": evidence_kind}
    if run_id is not None:
        after_state["evaluator_run_id"] = str(run_id)
    conn.execute(
        """
        INSERT INTO operations.audit_log
            (audit_id, actor_kind, source, action, entity_type, entity_id,
             before_state, after_state, user_agent, occurred_at, tenant_id)
        VALUES (gen_random_uuid(), 'system', 'ingest', 'lifecycle.transition', 'device',
                %s, %s::jsonb, %s::jsonb, '', now(), 1)
        """,
        (entity_id, json.dumps({"lifecycle_status": before}), json.dumps(after_state)),
    )


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)
            yield connection


def test_false_transitions_are_removed_and_real_ones_kept(conn):
    flapping, returning, aging = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pair_run, real_run, two_step_run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    # Pure noise: the run moved the Computer away and straight back.
    _transition(conn, flapping, pair_run, "pending_cleanup", "active", "source_evidence_restored")
    _transition(conn, flapping, pair_run, "active", "pending_cleanup", "direct_contact")
    # A real single transition.
    _transition(conn, returning, real_run, "pending_cleanup", "active", "source_evidence_restored")
    # A real change written through a false active.
    _transition(conn, aging, two_step_run, "offline_aging", "active", "source_evidence_restored")
    _transition(conn, aging, two_step_run, "active", "pending_cleanup", "direct_contact")
    # Older row without a run id, and an unrelated action: untouched.
    _transition(conn, flapping, None, "active", "offline_aging", "direct_contact")
    conn.execute(
        """
        INSERT INTO operations.audit_log
            (audit_id, actor_kind, source, action, entity_type, entity_id,
             user_agent, occurred_at, tenant_id)
        VALUES (gen_random_uuid(), 'user', 'ui', 'device.combine', 'device', %s, '', now(), 1)
        """,
        (aging,),
    )

    module = importlib.import_module("apps.core.migrations.0305_remove_lifecycle_transition_noise")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_migrate")
        conn.execute(module.FORWARD_SQL)

    rows = conn.execute(
        """
        SELECT entity_id, before_state->>'lifecycle_status', after_state->>'lifecycle_status',
               after_state->>'intermediate_transition_removed'
          FROM operations.audit_log
         WHERE action = 'lifecycle.transition'
         ORDER BY entity_id, before_state->>'lifecycle_status'
        """
    ).fetchall()
    by_entity: dict = {}
    for entity_id, before, after, marker in rows:
        by_entity.setdefault(entity_id, []).append((before, after, marker))

    assert by_entity[flapping] == [("active", "offline_aging", None)]
    assert by_entity[returning] == [("pending_cleanup", "active", None)]
    assert by_entity[aging] == [("offline_aging", "pending_cleanup", "0305")]

    assert (
        conn.execute(
            "SELECT count(*) FROM operations.audit_log WHERE action = 'device.combine'"
        ).fetchone()[0]
        == 1
    )
    cleanup = conn.execute(
        "SELECT after_state FROM operations.audit_log WHERE action = 'audit_log.cleanup'"
    ).fetchall()
    assert len(cleanup) == 1
    assert cleanup[0][0]["removed_rows"] == 2
    assert cleanup[0][0]["merged_transitions"] == 1


def test_running_again_changes_nothing(conn):
    module = importlib.import_module("apps.core.migrations.0305_remove_lifecycle_transition_noise")
    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    before = conn.execute("SELECT count(*) FROM operations.audit_log").fetchone()[0]
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_migrate")
        conn.execute(module.FORWARD_SQL)
    after = conn.execute("SELECT count(*) FROM operations.audit_log").fetchone()[0]
    assert after == before
