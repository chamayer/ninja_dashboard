"""Migrations 0362-0363 on a real PostgreSQL: additive findings expansion and tenant guard.

Tables use the production column types (local fresh-database catalog,
2026-10-29). 0306's change-history foundation is installed first because 0363
registers its new tables there. The migration SQL runs as ``operations_migrate``.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN SUPERUSER;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE SCHEMA operations AUTHORIZATION operations_migrate;
GRANT USAGE ON SCHEMA operations TO operations_app, operations_readonly, ninja_ingest;
CREATE TABLE operations.finding_types (
    id smallint PRIMARY KEY, name varchar(120) NOT NULL UNIQUE,
    default_severity varchar(16) NOT NULL, alertable boolean NOT NULL
);
CREATE TABLE operations.findings (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    subject_type varchar(32) NOT NULL, subject_id uuid NOT NULL,
    finding_details jsonb NOT NULL, severity varchar(16) NOT NULL, status varchar(24) NOT NULL,
    sla_due_at timestamptz NULL, first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL, last_reviewed_at timestamptz NULL,
    finding_type_id smallint NOT NULL REFERENCES operations.finding_types (id),
    owner_id bigint NULL, tenant_id bigint NOT NULL, client_id uuid NULL,
    condition_key varchar(255) NOT NULL, confidence varchar(16) NOT NULL,
    last_detected_at timestamptz NULL, snoozed_until timestamptz NULL,
    acknowledged_at timestamptz NULL, closed_at timestamptz NULL,
    subject_layer varchar(16) NOT NULL DEFAULT '', subject_layer_entity_id uuid NULL
);
CREATE UNIQUE INDEX uq_findings_active_condition_key_scope ON operations.findings
    (tenant_id, condition_key)
    WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');
CREATE TABLE operations.finding_state (
    finding_id uuid PRIMARY KEY REFERENCES operations.findings (id) ON DELETE CASCADE,
    tenant_id bigint NOT NULL, finding_type_id smallint NOT NULL, attention text NULL,
    reason text NOT NULL, covered_by uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    policy_version text NULL, computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE operations.source_action_requests (
    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL,
    finding_id uuid NOT NULL REFERENCES operations.findings (id),
    source_instance_id uuid NOT NULL, action_key text NOT NULL,
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
);
ALTER TABLE operations.finding_types OWNER TO operations_migrate;
ALTER TABLE operations.findings OWNER TO operations_migrate;
ALTER TABLE operations.finding_state OWNER TO operations_migrate;
ALTER TABLE operations.source_action_requests OWNER TO operations_migrate;
ALTER TABLE operations.findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.findings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.findings
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.findings TO operations_app, ninja_ingest;
GRANT SELECT ON operations.finding_types TO operations_app, ninja_ingest;
INSERT INTO operations.finding_types VALUES (1, 'missing_required_platform', 'high', true);
"""


def _sql(module_name: str) -> str:
    module = importlib.import_module(module_name)
    return module.Migration.operations[0].sql


@pytest.fixture(scope="module")
def dsn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    foundation = importlib.import_module("apps.core.migrations.0306_change_history_foundation")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(SCHEMA)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            # 0362 builds its index concurrently, so it runs outside a transaction.
            connection.execute("SET ROLE operations_migrate")
            connection.execute(_sql("apps.core.migrations.0362_findings_tenant_id_unique"))
            with connection.transaction():
                connection.execute(_sql("apps.core.migrations.0363_common_findings_expansion"))
            connection.execute("RESET ROLE")
        yield url


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield connection


def _finding(conn, tenant: int, *, key: str = "", status: str = "open", **extra) -> uuid.UUID:
    finding_id = uuid.uuid4()
    columns = {
        "version": 0,
        "id": finding_id,
        "subject_type": "device",
        "subject_id": uuid.uuid4(),
        "finding_details": "{}",
        "severity": "high",
        "status": status,
        "first_seen_at": "2026-10-29",
        "last_seen_at": "2026-10-29",
        "finding_type_id": 1,
        "tenant_id": tenant,
        "condition_key": key,
        "confidence": "",
    } | extra
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO operations.findings ({names}) VALUES ({marks})", list(columns.values())
    )
    return finding_id


def test_existing_writers_insert_without_the_new_columns(conn):
    finding_id = _finding(conn, 1, key="legacy-key")
    row = conn.execute(
        """SELECT subject_ref, condition_namespace, condition_identity, episode_key
             FROM operations.findings WHERE id = %s""",
        (finding_id,),
    ).fetchone()
    assert row == ({}, "entity", None, None)


def test_new_columns_reject_invalid_values(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        _finding(conn, 1, condition_namespace="other")
    with pytest.raises(psycopg.errors.CheckViolation):
        _finding(conn, 1, subject_ref="[]")
    with pytest.raises(psycopg.errors.CheckViolation):
        _finding(conn, 1, episode_key="")


def test_episode_key_is_unique_only_among_active_findings(conn):
    _finding(conn, 1, episode_key="approval:product-1", status="resolved")
    _finding(conn, 1, episode_key="approval:product-1")
    _finding(conn, 2, episode_key="approval:product-1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _finding(conn, 1, episode_key="approval:product-1", status="acknowledged")


def test_related_rows_cannot_point_at_another_tenants_finding(conn):
    finding_id = _finding(conn, 1)
    conn.execute(
        """INSERT INTO operations.finding_state (finding_id, tenant_id, finding_type_id, reason)
           VALUES (%s, 1, 1, 'ok')""",
        (finding_id,),
    )
    other = _finding(conn, 1)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """INSERT INTO operations.finding_state (finding_id, tenant_id, finding_type_id, reason)
               VALUES (%s, 2, 1, 'wrong tenant')""",
            (other,),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """INSERT INTO operations.source_action_requests
                   (tenant_id, finding_id, source_instance_id, action_key, external_id)
               VALUES (2, %s, %s, 'source.archive_hudu_asset', 'x')""",
            (finding_id, uuid.uuid4()),
        )


def test_relationships_enforce_tenant_endpoints_and_are_read_only_to_runtime_roles(conn):
    parent, child, foreign = _finding(conn, 1), _finding(conn, 1), _finding(conn, 2)
    conn.execute(
        """INSERT INTO operations.finding_relationship_rules
               (parent_type_id, child_type_id, kind, scope_matcher, parent_satisfaction)
           VALUES (1, 1, 'covers', 'same_computer', 'parent_open')"""
    )
    rule_id = conn.execute("SELECT max(id) FROM operations.finding_relationship_rules").fetchone()[
        0
    ]
    insert = """INSERT INTO operations.finding_relationships
                    (tenant_id, rule_id, parent_id, child_id, kind, scope_fingerprint)
                VALUES (1, %s, %s, %s, 'covers', 'fp')"""
    conn.execute(insert, (rule_id, parent, child))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(insert, (rule_id, parent, foreign))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(insert, (rule_id, parent, parent))
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '2', true)")
        assert conn.execute("SELECT count(*) FROM operations.finding_relationships").fetchone() == (
            0,
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        conn.execute(insert, (rule_id, child, parent))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute(
            "INSERT INTO operations.finding_action_registry VALUES ('condition.execute', 'system_effect')"
        )


def test_new_tables_are_classified_and_configuration_gets_history(conn):
    unclassified = {
        row[0] for row in conn.execute("SELECT operations.change_history_unclassified()").fetchall()
    }
    assert not unclassified & {
        "finding_legacy_refs",
        "finding_relationships",
        "finding_action_registry",
        "finding_relationship_rules",
        "finding_relationship_rule_actions",
    }
    for table in (
        "finding_action_registry",
        "finding_relationship_rules",
        "finding_relationship_rule_actions",
    ):
        assert conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (f"operations.{table}_change_history",)
        ).fetchone()[0]


def _guard(conn, tenant: str, mode: str) -> None:
    conn.execute("SELECT set_config('operations.tenant_id', %s, true)", (tenant,))
    conn.execute("SELECT operations.acquire_tenant_guard(%s, %s)", (int(tenant), mode))


def test_tenant_guard_shares_excludes_and_refuses_upgrades(dsn):
    with psycopg.connect(dsn) as a, psycopg.connect(dsn) as b:
        for c in (a, b):
            c.execute("SET ROLE operations_app")
            c.execute("SET lock_timeout = '200ms'")
            c.commit()
        _guard(a, "1", "shared")
        _guard(b, "1", "shared")
        assert a.execute("SELECT operations.tenant_guard_mode(1)").fetchone() == ("shared",)
        b.rollback()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            _guard(b, "1", "exclusive")
        b.rollback()
        _guard(b, "2", "exclusive")
        assert b.execute("SELECT operations.tenant_guard_mode(2)").fetchone() == ("exclusive",)
        b.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="cannot be upgraded"):
            a.execute("SELECT operations.acquire_tenant_guard(1, 'exclusive')")
        a.rollback()
        assert a.execute("SELECT operations.tenant_guard_mode(1)").fetchone() == (None,)


def test_tenant_guard_assertion_and_input_checks(dsn):
    with psycopg.connect(dsn) as c:
        c.execute("SET ROLE operations_app")
        c.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="needs the session tenant"):
            c.execute("SELECT set_config('operations.tenant_id', '1', true)")
            c.execute("SELECT operations.acquire_tenant_guard(2, 'shared')")
        c.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="shared or exclusive"):
            _guard(c, "1", "read")
        c.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="must be held"):
            c.execute("SELECT operations.assert_tenant_guard(1, 'shared')")
        c.rollback()
        _guard(c, "1", "shared")
        c.execute("SELECT operations.assert_tenant_guard(1, 'shared')")
        with pytest.raises(psycopg.errors.RaiseException, match="exclusive mode"):
            c.execute("SELECT operations.assert_tenant_guard(1, 'exclusive')")
        c.rollback()
        _guard(c, "1", "exclusive")
        c.execute("SELECT operations.assert_tenant_guard(1, 'exclusive')")
        c.execute("SELECT operations.assert_tenant_guard(1, 'shared')")
        c.rollback()


def test_tenant_guard_is_not_executable_by_unlisted_roles(dsn):
    with psycopg.connect(dsn) as c:
        c.execute("SET ROLE operations_readonly")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT operations.acquire_tenant_guard(1, 'shared')")
