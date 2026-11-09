"""PostgreSQL coverage for the PLAN-044 batched source-client evidence reader."""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import psycopg
import pytest

from apps.core import issue_selection
from apps.core.issue_selection import Scope

SCHEMA = """
CREATE SCHEMA operations;
CREATE ROLE operations_migrate;
CREATE ROLE operations_app;
CREATE ROLE operations_readonly;
CREATE ROLE ninja_ingest;
CREATE TABLE operations.clients (
    tenant_id bigint NOT NULL, id uuid NOT NULL, deleted_at timestamptz,
    display_name text NOT NULL DEFAULT '', PRIMARY KEY (tenant_id, id)
);
CREATE TABLE operations.source_instances (
    tenant_id bigint NOT NULL, id uuid NOT NULL, client_id uuid,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE operations.entity_observation_current (
    tenant_id bigint NOT NULL, observation_id uuid NOT NULL,
    source_instance_id uuid, entity_type text, external_id text,
    external_namespace text, parent_external_namespace text,
    parent_external_id text, entity_key text, canonical_data jsonb NOT NULL DEFAULT '{}',
    active boolean NOT NULL DEFAULT true, PRIMARY KEY (tenant_id, observation_id)
);
CREATE TABLE operations.entity_source_links (
    tenant_id bigint NOT NULL, id uuid PRIMARY KEY, source_instance_id uuid NOT NULL,
    entity_class_id text NOT NULL, entity_id uuid NOT NULL, external_id text NOT NULL,
    external_namespace text NOT NULL, parent_external_namespace text NOT NULL,
    parent_external_id text NOT NULL, missing_since timestamptz
);
CREATE TABLE operations.client_source_mapping_decisions (
    tenant_id bigint NOT NULL, source_link_id uuid NOT NULL, state text NOT NULL,
    provenance text NOT NULL, decided_at timestamptz NOT NULL, superseded_at timestamptz
);
CREATE TABLE operations.entity_source_link_history (
    tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL,
    external_namespace text NOT NULL, parent_external_namespace text,
    parent_external_id text, external_id text NOT NULL, entity_class_id text NOT NULL,
    entity_id uuid NOT NULL, effective_to timestamptz, effective_from timestamptz NOT NULL
);
CREATE TABLE operations.test_name_proof (link_id uuid PRIMARY KEY, proved boolean NOT NULL);
GRANT USAGE ON SCHEMA operations TO operations_migrate;
GRANT SELECT ON ALL TABLES IN SCHEMA operations TO operations_migrate;
CREATE FUNCTION operations.computer_client_group_name_proved(p_tenant bigint, p_link uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT coalesce((SELECT proof.proved FROM operations.test_name_proof proof
                      WHERE proof.link_id = p_link), false)
$fn$;
ALTER FUNCTION operations.computer_client_group_name_proved(bigint, uuid)
    OWNER TO operations_migrate;
GRANT EXECUTE ON FUNCTION operations.computer_client_group_name_proved(bigint, uuid)
    TO operations_migrate;
"""


@pytest.fixture(scope="module")
def dsn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    migration_path = (
        Path(__file__).resolve().parents[1] / "migrations" / "0406_batch_source_client_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("plan044_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(SCHEMA)
            connection.execute(migration.FORWARD_SQL)
        yield url


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn) as connection:
        yield connection
        connection.rollback()


def _client(conn, *, deleted=False):
    client_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.clients (tenant_id, id, deleted_at) "
        "VALUES (1, %s, CASE WHEN %s THEN now() END)",
        [client_id, deleted],
    )
    return client_id


def _observation(
    conn,
    instance_id,
    *,
    kind="device",
    group_id="GROUP",
    external_id="RECORD",
    namespace="rmm",
    parent_namespace="org",
    parent_id="root",
    entity_key=None,
    active=True,
):
    observation_id = uuid.uuid4()
    canonical = {"platform_group_id": group_id} if kind != "org" else {}
    conn.execute(
        """INSERT INTO operations.entity_observation_current
           (tenant_id, observation_id, source_instance_id, entity_type, external_id,
            external_namespace, parent_external_namespace, parent_external_id,
            entity_key, canonical_data, active)
           VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
        [
            observation_id,
            instance_id,
            kind,
            external_id,
            namespace,
            parent_namespace,
            parent_id,
            entity_key,
            psycopg.types.json.Jsonb(canonical),
            active,
        ],
    )
    return observation_id


def _group_link(
    conn,
    instance_id,
    group_id,
    client_id,
    *,
    mode,
    proved=True,
    duplicate=0,
    decided_at="2026-01-02 UTC",
    history_from="2026-01-01 UTC",
):
    link_ids = []
    for _index in range(duplicate + 1):
        link_id = uuid.uuid4()
        link_ids.append(link_id)
        conn.execute(
            """INSERT INTO operations.entity_source_links
               (tenant_id, id, source_instance_id, entity_class_id, entity_id,
                external_id, external_namespace, parent_external_namespace, parent_external_id)
               VALUES (1, %s, %s, 'client', %s, %s, 'rmm', 'org', 'root')""",
            [link_id, instance_id, client_id, group_id],
        )
        conn.execute(
            """INSERT INTO operations.entity_source_link_history
               (tenant_id, source_instance_id, external_namespace, external_id,
                parent_external_namespace, parent_external_id,
                entity_class_id, entity_id, effective_from)
               VALUES (1, %s, 'rmm', %s, 'org', 'root', 'client', %s, %s)""",
            [instance_id, group_id, client_id, history_from],
        )
        state, provenance = (
            ("explicit", "operator") if mode == "operator" else ("automatic", "resolver")
        )
        conn.execute(
            """INSERT INTO operations.client_source_mapping_decisions
               (tenant_id, source_link_id, state, provenance, decided_at)
               VALUES (1, %s, %s, %s, %s)""",
            [link_id, state, provenance, decided_at],
        )
        conn.execute("INSERT INTO operations.test_name_proof VALUES (%s, %s)", [link_id, proved])
    return link_ids


def test_batch_preserves_direct_operator_and_automatic_attribution(conn):
    client_one, client_two, deleted_client = (
        _client(conn),
        _client(conn),
        _client(conn, deleted=True),
    )
    direct_instance, deleted_instance, group_instance = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.source_instances VALUES (1, %s, %s), (1, %s, %s), (1, %s, NULL)",
        [direct_instance, client_one, deleted_instance, deleted_client, group_instance],
    )
    direct = _observation(conn, direct_instance)
    deleted_direct = _observation(conn, deleted_instance)

    operator_org = _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="OP-GROUP",
        entity_key="OP-GROUP",
    )
    operator_record = _observation(conn, group_instance, group_id="OP-GROUP")
    _group_link(conn, group_instance, "OP-GROUP", client_two, mode="operator")

    automatic_org = _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="AUTO-GROUP",
        entity_key="AUTO-GROUP",
    )
    automatic_record = _observation(conn, group_instance, group_id="AUTO-GROUP")
    _group_link(conn, group_instance, "AUTO-GROUP", client_one, mode="automatic")

    unproved_org = _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="UNPROVED",
        entity_key="UNPROVED",
    )
    unproved_record = _observation(conn, group_instance, group_id="UNPROVED")
    _group_link(conn, group_instance, "UNPROVED", client_one, mode="automatic", proved=False)

    ambiguous_record = _observation(conn, group_instance, group_id="AMBIGUOUS")
    _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="AMBIGUOUS",
        entity_key="AMBIGUOUS",
    )
    _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="AMBIGUOUS-2",
        entity_key="AMBIGUOUS",
    )
    _group_link(conn, group_instance, "AMBIGUOUS", client_two, mode="operator")

    duplicate_record = _observation(conn, group_instance, group_id="DUPLICATE")
    _observation(
        conn,
        group_instance,
        kind="org",
        group_id=None,
        external_id="DUPLICATE",
        entity_key="DUPLICATE",
    )
    _group_link(conn, group_instance, "DUPLICATE", client_one, mode="operator", duplicate=1)

    stale_record = _observation(conn, group_instance, group_id="STALE")
    _observation(
        conn, group_instance, kind="org", group_id=None, external_id="STALE", entity_key="STALE"
    )
    _group_link(
        conn,
        group_instance,
        "STALE",
        client_two,
        mode="operator",
        decided_at="2025-12-31 UTC",
    )

    observations = [
        direct,
        direct,
        deleted_direct,
        operator_org,
        operator_record,
        automatic_org,
        automatic_record,
        unproved_org,
        unproved_record,
        ambiguous_record,
        duplicate_record,
        stale_record,
        uuid.uuid4(),
    ]
    with conn.transaction():
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        rows = conn.execute(
            "SELECT observation_id, client_id "
            "FROM operations.computer_client_independent_evidence_batch(1, %s)",
            [observations],
        ).fetchall()

    assert dict(rows) == {
        direct: client_one,
        deleted_direct: None,
        operator_org: client_two,
        operator_record: client_two,
        automatic_org: client_one,
        automatic_record: client_one,
        unproved_org: None,
        unproved_record: None,
        ambiguous_record: None,
        duplicate_record: None,
        stale_record: None,
        observations[-1]: None,
    }


def test_batch_requires_matching_tenant_and_is_granted_only_to_app(conn):
    observation_id = uuid.uuid4()
    with conn.transaction():
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        with pytest.raises(psycopg.Error, match="tenant context mismatch"):
            conn.execute(
                "SELECT * FROM operations.computer_client_independent_evidence_batch(2, %s)",
                [[observation_id]],
            )
    assert conn.execute(
        "SELECT has_function_privilege('operations_app', "
        "'operations.computer_client_independent_evidence_batch(bigint,uuid[])', 'EXECUTE'), "
        "has_function_privilege('operations_readonly', "
        "'operations.computer_client_independent_evidence_batch(bigint,uuid[])', 'EXECUTE'), "
        "has_function_privilege('ninja_ingest', "
        "'operations.computer_client_independent_evidence_batch(bigint,uuid[])', 'EXECUTE')"
    ).fetchone() == (True, False, False)


def test_home_compact_selection_uses_batched_attribution():
    sql, params = issue_selection._filtered_sql(
        Scope(status="open_paused"), summary=True, home_compact=True
    )

    assert "computer_client_independent_evidence_batch" in sql
    assert "computer_client_independent_evidence(" not in sql
    assert params["tenant"] == 1
