"""Resolver history repair skips equal rows while retaining its repair scope."""

from __future__ import annotations

import importlib
import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from ingest import relationships

SCHEMA = """
CREATE SCHEMA operations;
CREATE ROLE ninja_ingest NOLOGIN;
GRANT USAGE ON SCHEMA operations TO ninja_ingest;
CREATE FUNCTION operations.current_tenant_id() RETURNS bigint LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('operations.tenant_id', true), '')::bigint
$$;
CREATE TABLE operations.entities (tenant_id bigint, id uuid, entity_class_id text);
CREATE TABLE operations.relationship_types (
    key text, source_entity_class_id text, target_entity_class_id text
);
INSERT INTO operations.relationship_types VALUES ('fixture', 'device', 'device');
CREATE TABLE operations.relationship_authority_policies (
    tenant_id bigint, source_instance_id uuid, native_record_type text,
    relationship_type_id text, enabled boolean, eligible boolean,
    authority_tier smallint, priority smallint
);
CREATE TABLE operations.entity_source_links (
    tenant_id bigint, source_instance_id uuid, entity_id uuid,
    external_namespace text, parent_external_namespace text,
    parent_external_id text, external_id text
);
CREATE TABLE operations.operating_system_installation_source_identities (
    tenant_id bigint, source_instance_id uuid, parent_external_namespace text,
    parent_external_id text, external_id text, installation_id uuid
);
CREATE TABLE operations.operating_system_installations (
    tenant_id bigint, id uuid, entity_id uuid
);
CREATE TABLE operations.entity_relationship_evidence_current (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, version integer DEFAULT 1,
    source_instance_id uuid, native_record_type text DEFAULT 'fixture',
    relationship_type_id text DEFAULT 'fixture',
    source_endpoint_source_instance_id uuid, source_external_namespace text DEFAULT '',
    source_parent_external_namespace text DEFAULT '', source_parent_external_id text DEFAULT '',
    source_external_id text DEFAULT 'source',
    target_endpoint_source_instance_id uuid, target_external_namespace text DEFAULT '',
    target_parent_external_namespace text DEFAULT '', target_parent_external_id text DEFAULT '',
    target_external_id text DEFAULT 'target',
    source_entity_id uuid, target_entity_id uuid, active boolean DEFAULT true,
    resolution_status text NOT NULL DEFAULT 'unresolved',
    authority_eligible boolean NOT NULL DEFAULT false,
    authority_tier smallint NOT NULL DEFAULT 0, authority_priority smallint NOT NULL DEFAULT 0,
    material_hash bytea DEFAULT '\\x01', withdrawn_at timestamptz
);
CREATE TABLE operations.entity_relationship_evidence_history (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, evidence_current_id uuid NOT NULL,
    source_entity_id uuid, target_entity_id uuid, resolution_status text NOT NULL,
    authority_eligible boolean NOT NULL, authority_tier smallint NOT NULL,
    authority_priority smallint NOT NULL, material_hash bytea DEFAULT '\\x01',
    effective_from timestamptz NOT NULL DEFAULT now(), effective_to timestamptz
);
CREATE UNIQUE INDEX one_open_history ON operations.entity_relationship_evidence_history
    (tenant_id, evidence_current_id) WHERE effective_to IS NULL;
CREATE TABLE operations.entity_relationship_dirty (
    id uuid PRIMARY KEY, tenant_id bigint, version integer, relationship_type_id varchar,
    source_entity_id uuid, target_entity_id uuid, queued_at timestamptz, reason varchar,
    UNIQUE (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
);
GRANT SELECT ON ALL TABLES IN SCHEMA operations TO ninja_ingest;
GRANT UPDATE ON operations.entity_relationship_evidence_current,
    operations.entity_relationship_evidence_history TO ninja_ingest;
"""

FIELDS = (
    "source_entity_id",
    "target_entity_id",
    "resolution_status",
    "authority_eligible",
    "authority_tier",
    "authority_priority",
)


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for disposable PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    migration = importlib.import_module(
        "apps.core.migrations.0111_relationship_candidate_event_contracts"
    )
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA)
            # Use the existing validator and queue functions for current writes.
            start = migration.TRIGGER_SQL.index(
                "CREATE OR REPLACE FUNCTION operations.validate_relationship_evidence()"
            )
            end = migration.TRIGGER_SQL.index(
                "CREATE OR REPLACE FUNCTION operations.audit_and_queue_relationship_decision()"
            )
            conn.execute(migration.TRIGGER_SQL[start:end])
            conn.execute("""
                CREATE TRIGGER validate_relationship_evidence BEFORE INSERT OR UPDATE
                ON operations.entity_relationship_evidence_current FOR EACH ROW
                EXECUTE FUNCTION operations.validate_relationship_evidence();
                CREATE TRIGGER queue_relationship_evidence AFTER INSERT OR UPDATE OR DELETE
                ON operations.entity_relationship_evidence_current FOR EACH ROW
                EXECUTE FUNCTION operations.queue_relationship_evidence();
            """)
            for table in (
                "entity_relationship_evidence_current",
                "entity_relationship_evidence_history",
            ):
                conn.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
                conn.execute(f"ALTER TABLE operations.{table} FORCE ROW LEVEL SECURITY")
                conn.execute(
                    f"CREATE POLICY tenant_isolation ON operations.{table} "
                    "USING (tenant_id = operations.current_tenant_id()) "
                    "WITH CHECK (tenant_id = operations.current_tenant_id())"
                )
            yield conn


@pytest.fixture
def conn(database, monkeypatch):
    @contextmanager
    def transaction():
        with database.transaction(), database.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE ninja_ingest")
            yield cursor
            cursor.execute("RESET ROLE")

    monkeypatch.setattr(relationships.db, "transaction", transaction)
    with database.transaction(force_rollback=True):
        yield database


def _record(conn, *, pending=False, tenant=1, missing_endpoint=None):
    evidence, instance, source, target = (uuid.uuid4() for _ in range(4))
    for name, entity in (("source", source), ("target", target)):
        conn.execute("INSERT INTO operations.entities VALUES (%s, %s, 'device')", (tenant, entity))
        if name != missing_endpoint:
            conn.execute(
                "INSERT INTO operations.entity_source_links VALUES (%s, %s, %s, '', '', '', %s)",
                (tenant, instance, entity, name),
            )
    conn.execute(
        """INSERT INTO operations.entity_relationship_evidence_current
           (id, tenant_id, source_instance_id, source_endpoint_source_instance_id,
            target_endpoint_source_instance_id, source_entity_id, target_entity_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            evidence,
            tenant,
            instance,
            instance,
            instance,
            None if pending or missing_endpoint == "source" else source,
            None if pending or missing_endpoint == "target" else target,
        ),
    )
    conn.execute(
        f"""INSERT INTO operations.entity_relationship_evidence_history
            (id, tenant_id, evidence_current_id, {', '.join(FIELDS)})
            SELECT id, tenant_id, id, {', '.join(FIELDS)}
            FROM operations.entity_relationship_evidence_current WHERE id = %s""",
        (evidence,),
    )
    return evidence


def _history(conn, evidence):
    return conn.execute(
        "SELECT ctid::text, to_jsonb(history) FROM operations.entity_relationship_evidence_history history "
        "WHERE id = %s",
        (evidence,),
    ).fetchone()


@pytest.mark.integration
def test_resolver_skips_equal_rows_and_preserves_closed_and_other_tenant_history(conn):
    pending = _record(conn, pending=True)
    equal = _record(conn)
    other = _record(conn, tenant=2)
    conn.execute(
        "UPDATE operations.entity_relationship_evidence_history SET authority_tier = 9 WHERE id = %s",
        (other,),
    )
    closed = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.entity_relationship_evidence_history
           SELECT %s, tenant_id, evidence_current_id, source_entity_id, target_entity_id,
                  resolution_status, authority_eligible, authority_tier, authority_priority,
                  material_hash, effective_from, effective_from + interval '1 second'
           FROM operations.entity_relationship_evidence_history WHERE id = %s""",
        (closed, pending),
    )
    before = {key: _history(conn, key) for key in (equal, other, closed)}
    assert relationships.resolve_current_evidence() == 1
    assert {key: _history(conn, key) for key in before} == before
    row = _history(conn, pending)[1]
    assert row["resolution_status"] == "resolved"
    assert row["source_entity_id"] and row["target_entity_id"]
    assert (
        conn.execute("SELECT count(*) FROM operations.entity_relationship_dirty").fetchone()[0] >= 1
    )
    after = _history(conn, pending)
    assert relationships.resolve_current_evidence() == 0
    assert _history(conn, pending) == after


@pytest.mark.integration
@pytest.mark.parametrize("field", FIELDS)
def test_resolver_repairs_each_stale_field_outside_changed_endpoint_ids(conn, field):
    _record(conn, pending=True)  # Opens the existing nonzero-resolution gate.
    stale = _record(conn)
    expected = _history(conn, stale)[1]
    replacement = (
        None
        if field.endswith("entity_id")
        else {
            "resolution_status": "unresolved",
            "authority_eligible": True,
            "authority_tier": 9,
            "authority_priority": 9,
        }[field]
    )
    conn.execute(
        f"UPDATE operations.entity_relationship_evidence_history SET {field} = %s WHERE id = %s",
        (replacement, stale),
    )
    assert relationships.resolve_current_evidence() == 1
    assert _history(conn, stale)[1] == expected


@pytest.mark.integration
@pytest.mark.parametrize("endpoint", ("source", "target"))
def test_resolver_repairs_stale_nonnull_endpoint_to_null(conn, endpoint):
    _record(conn, pending=True)
    stale = _record(conn, missing_endpoint=endpoint)
    expected = _history(conn, stale)[1]
    conn.execute(
        f"UPDATE operations.entity_relationship_evidence_history SET {endpoint}_entity_id = %s WHERE id = %s",
        (uuid.uuid4(), stale),
    )
    assert relationships.resolve_current_evidence() == 1
    assert _history(conn, stale)[1] == expected


@pytest.mark.integration
def test_resolver_keeps_history_gate_when_no_endpoint_changes(conn):
    stale = _record(conn)
    conn.execute(
        "UPDATE operations.entity_relationship_evidence_history SET authority_tier = 9 WHERE id = %s",
        (stale,),
    )
    before = _history(conn, stale)
    assert relationships.resolve_current_evidence() == 0
    assert _history(conn, stale) == before
