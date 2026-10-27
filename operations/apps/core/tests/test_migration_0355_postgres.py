"""Migration 0355 candidate lifecycle behavior on an isolated PostgreSQL."""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

MODULE = "apps.core.migrations.0355_entity_candidate_withdrawal"

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN SUPERUSER BYPASSRLS;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE SCHEMA operations;
CREATE TABLE operations.entity_types (
    name text PRIMARY KEY, entity_class_id text NOT NULL
);
CREATE TABLE operations.identity_authority_policies (
    tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL,
    native_record_type text NOT NULL, resulting_entity_type_id text NOT NULL,
    enabled boolean NOT NULL, may_establish_identity boolean NOT NULL
);
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
    source_instance_id uuid NOT NULL, entity_type text NOT NULL,
    external_namespace text NOT NULL,
    parent_external_namespace text NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    active boolean NOT NULL, material_hash bytea NOT NULL,
    client_id uuid, observed_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL
);
CREATE TABLE operations.entities (
    tenant_id bigint NOT NULL, id uuid NOT NULL, entity_class_id text NOT NULL,
    PRIMARY KEY (tenant_id, id, entity_class_id)
);
CREATE TABLE operations.entity_source_links (
    tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL,
    external_namespace text NOT NULL,
    parent_external_namespace text NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    entity_id uuid NOT NULL, entity_class_id text NOT NULL,
    UNIQUE (tenant_id, source_instance_id, external_namespace,
            parent_external_namespace, parent_external_id, external_id),
    FOREIGN KEY (tenant_id, entity_id, entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
);
CREATE TABLE operations.entity_candidates (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, version integer NOT NULL,
    source_instance_id uuid NOT NULL, proposed_entity_class_id text NOT NULL,
    client_id uuid, external_namespace text NOT NULL,
    parent_external_namespace text NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    status text NOT NULL, material_hash bytea,
    resolved_entity_id uuid, latest_decision text NOT NULL DEFAULT '',
    latest_decision_reason text NOT NULL DEFAULT '', latest_decided_at timestamptz,
    first_observed_at timestamptz NOT NULL, last_observed_at timestamptz NOT NULL,
    UNIQUE (tenant_id, source_instance_id, external_namespace,
            parent_external_namespace, parent_external_id, external_id,
            proposed_entity_class_id),
    FOREIGN KEY (tenant_id, resolved_entity_id, proposed_entity_class_id)
        REFERENCES operations.entities (tenant_id, id, entity_class_id)
);
CREATE TABLE operations.entity_candidate_events (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, version integer NOT NULL,
    candidate_id uuid NOT NULL, action text NOT NULL, actor_kind text NOT NULL,
    actor_process text NOT NULL, reason text NOT NULL,
    before_state jsonb, after_state jsonb, occurred_at timestamptz NOT NULL
);
CREATE FUNCTION operations.sync_entity_candidates(batch_size integer DEFAULT 500)
RETURNS TABLE(created integer, reopened integer, attached integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = operations, pg_temp
AS $function$ BEGIN created := 0; reopened := 0; attached := 0; RETURN NEXT; END; $function$;
"""


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
            module = importlib.import_module(MODULE)
            connection.execute(module.FORWARD_SQL)
            yield connection


def _candidate(conn, *, status="observed_only", active=True, link_class=None):
    tenant_id = 1
    source_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    identity = uuid.uuid4().hex
    observation_id = uuid.uuid4()
    observed = "2026-10-27 00:00:00+00"
    external_namespace = "agent.rmm"
    material_hash = b"same-material"
    conn.execute(
        "INSERT INTO operations.entity_types VALUES (%s, 'device') "
        "ON CONFLICT (name) DO NOTHING",
        (external_namespace,),
    )
    conn.execute(
        """INSERT INTO operations.entity_observation_current
           VALUES (%s, %s, %s, %s, %s, '', '', %s, %s, %s, NULL, %s, %s)""",
        (
            observation_id,
            tenant_id,
            source_id,
            external_namespace,
            external_namespace,
            identity,
            active,
            material_hash,
            observed,
            observed,
        ),
    )
    conn.execute(
        """INSERT INTO operations.entity_candidates
           (id, tenant_id, version, source_instance_id, proposed_entity_class_id,
            external_namespace, external_id, status, material_hash,
            first_observed_at, last_observed_at)
           VALUES (%s, %s, 1, %s, 'device', %s, %s, %s, %s, %s, %s)""",
        (
            candidate_id,
            tenant_id,
            source_id,
            external_namespace,
            identity,
            status,
            material_hash,
            observed,
            observed,
        ),
    )
    entity_id = None
    if link_class:
        entity_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO operations.entities VALUES (%s, %s, %s)",
            (tenant_id, entity_id, link_class),
        )
        conn.execute(
            """INSERT INTO operations.entity_source_links
               (tenant_id, source_instance_id, external_namespace,
                parent_external_namespace, parent_external_id, external_id,
                entity_id, entity_class_id)
               VALUES (%s, %s, %s, '', '', %s, %s, %s)""",
            (tenant_id, source_id, external_namespace, identity, entity_id, link_class),
        )
    return candidate_id, observation_id, entity_id


def _status(conn, candidate_id):
    return conn.execute(
        "SELECT status, resolved_entity_id FROM operations.entity_candidates WHERE id=%s",
        (candidate_id,),
    ).fetchone()


def test_projector_functions_keep_security_definer_and_limited_grants(conn):
    rows = conn.execute(
        """SELECT procedure.proname, procedure.prosecdef,
                  pg_get_userbyid(procedure.proowner),
                  has_function_privilege('ninja_ingest', procedure.oid, 'EXECUTE'),
                  has_function_privilege('operations_app', procedure.oid, 'EXECUTE'),
                  COALESCE(bool_or(acl.grantee = 0), false) AS public_execute
             FROM pg_catalog.pg_proc procedure
             JOIN pg_catalog.pg_namespace namespace ON namespace.oid=procedure.pronamespace
             CROSS JOIN LATERAL aclexplode(procedure.proacl) acl
            WHERE namespace.nspname='operations'
              AND procedure.proname IN
                  ('sync_entity_candidates', 'sync_entity_candidates_v2')
            GROUP BY procedure.oid ORDER BY procedure.proname"""
    ).fetchall()
    assert rows == [
        ("sync_entity_candidates", True, "operations_migrate", True, True, False),
        ("sync_entity_candidates_v2", True, "operations_migrate", True, True, False),
    ]


def test_withdrawals_are_audited_and_idempotent(conn):
    conflict_id, _, _ = _candidate(conn, link_class="asset")
    inactive_id, _, _ = _candidate(conn, active=False, status="pending")

    assert conn.execute("SELECT * FROM operations.sync_entity_candidates_v2(10)").fetchone() == (
        0,
        0,
        0,
        2,
    )
    assert _status(conn, conflict_id) == ("withdrawn", None)
    assert _status(conn, inactive_id) == ("withdrawn", None)
    reasons = conn.execute(
        "SELECT reason FROM operations.entity_candidate_events "
        "WHERE candidate_id = ANY(%s::uuid[]) ORDER BY reason",
        ([conflict_id, inactive_id],),
    ).fetchall()
    assert reasons == [
        ("source observation is inactive and no source link exists",),
        ("stable source identity is linked to a different entity class",),
    ]
    event_count = conn.execute(
        "SELECT count(*) FROM operations.entity_candidate_events"
    ).fetchone()[0]
    assert conn.execute("SELECT * FROM operations.sync_entity_candidates_v2(10)").fetchone() == (
        0,
        0,
        0,
        0,
    )
    assert (
        conn.execute("SELECT count(*) FROM operations.entity_candidate_events").fetchone()[0]
        == event_count
    )


def test_matching_links_attach_but_rejected_and_attached_are_preserved(conn):
    linked_id, _, entity_id = _candidate(conn, status="pending", link_class="device")
    rejected_id, _, _ = _candidate(conn, status="rejected", link_class="device")
    attached_id, _, _ = _candidate(conn, status="attached")

    assert conn.execute("SELECT * FROM operations.sync_entity_candidates_v2(10)").fetchone() == (
        0,
        0,
        1,
        0,
    )
    assert _status(conn, linked_id) == ("attached", entity_id)
    assert _status(conn, rejected_id) == ("rejected", None)
    assert _status(conn, attached_id) == ("attached", None)


def test_active_unlinked_withdrawal_reopens_once(conn):
    candidate_id, observation_id, _ = _candidate(conn, active=False)
    assert conn.execute("SELECT * FROM operations.sync_entity_candidates_v2(10)").fetchone() == (
        0,
        0,
        0,
        1,
    )
    conn.execute(
        "UPDATE operations.entity_observation_current SET active=true WHERE observation_id=%s",
        (observation_id,),
    )

    assert conn.execute("SELECT * FROM operations.sync_entity_candidates_v2(10)").fetchone() == (
        0,
        1,
        0,
        0,
    )
    assert _status(conn, candidate_id) == ("observed_only", None)
    assert conn.execute(
        "SELECT action, reason FROM operations.entity_candidate_events "
        "WHERE candidate_id=%s ORDER BY occurred_at",
        (candidate_id,),
    ).fetchall() == [
        ("withdraw", "source observation is inactive and no source link exists"),
        ("reopen", "source observation became active"),
    ]


def test_legacy_wrapper_drains_withdrawals_without_changing_its_result_shape(conn):
    first_id, _, _ = _candidate(conn, link_class="asset")
    second_id, _, _ = _candidate(conn, active=False)

    assert conn.execute("SELECT * FROM operations.sync_entity_candidates(1)").fetchone() == (
        0,
        0,
        0,
    )
    assert _status(conn, first_id)[0] == "withdrawn"
    assert _status(conn, second_id)[0] == "withdrawn"
