"""Opt-in PostgreSQL integration coverage for Track A.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. The test uses a disposable
Postgres container; it never connects to a configured Operations environment.
"""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from ingest.evaluator import _sync_lifecycle_status


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield conn


def _prepare_track_a_schema(conn) -> None:
    migration = importlib.import_module(
        "operations.apps.core.migrations.0093_lifecycle_evidence_policy_and_audit"
    )
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA operations")
        cur.execute("CREATE ROLE operations_app")
        cur.execute("CREATE ROLE ninja_ingest")
        cur.execute("""
            CREATE TABLE operations.entity_types (
                name varchar(80) PRIMARY KEY,
                is_identity_signal boolean NOT NULL DEFAULT false,
                description text NOT NULL DEFAULT ''
            );
            CREATE TABLE operations.platform_aliases (
                alias varchar(80) PRIMARY KEY,
                canonical varchar(80) NOT NULL
            );
            CREATE TABLE operations.audit_log (
                audit_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                actor_id uuid NULL,
                actor_kind varchar(16) NOT NULL,
                source varchar(32) NOT NULL,
                action varchar(120) NOT NULL,
                entity_type varchar(80) NOT NULL,
                entity_id uuid NULL,
                before_state jsonb NULL,
                after_state jsonb NULL,
                ip_address inet NULL,
                user_agent text NOT NULL DEFAULT '',
                occurred_at timestamptz NOT NULL
            );
            CREATE TABLE operations.finding_categories (
                id smallint PRIMARY KEY,
                name varchar(32) UNIQUE NOT NULL
            );
            CREATE TABLE operations.finding_types (
                id smallint PRIMARY KEY,
                name varchar(120) UNIQUE NOT NULL,
                default_severity varchar(16) NOT NULL,
                runbook_path varchar(255) NOT NULL DEFAULT '',
                description text NOT NULL DEFAULT '',
                finding_class varchar(16) NOT NULL,
                source_module varchar(80) NOT NULL DEFAULT '',
                auto_resolvable boolean NOT NULL,
                category_id smallint NOT NULL REFERENCES operations.finding_categories(id)
            );
            CREATE TABLE operations.findings (
                id uuid PRIMARY KEY,
                version integer NOT NULL,
                tenant_id bigint NOT NULL,
                finding_type_id smallint NOT NULL REFERENCES operations.finding_types(id),
                client_id uuid NULL,
                subject_type varchar(32) NOT NULL,
                subject_id uuid NOT NULL,
                subject_layer varchar(80) NOT NULL DEFAULT '',
                finding_details jsonb NOT NULL DEFAULT '{}',
                condition_key varchar(255) NOT NULL,
                severity varchar(16) NOT NULL,
                confidence varchar(16) NOT NULL,
                status varchar(24) NOT NULL,
                first_seen_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                last_detected_at timestamptz NOT NULL
            );
            CREATE UNIQUE INDEX findings_open_condition_key
                ON operations.findings (tenant_id, condition_key)
                WHERE condition_key > '' AND status IN ('open', 'acknowledged');
            CREATE TABLE operations.devices (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                client_id uuid NOT NULL,
                lifecycle_status varchar(24) NOT NULL,
                deleted_at timestamptz NULL
            );
            CREATE TABLE operations.device_agent_presence_current (
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                entity_type varchar(80) NOT NULL,
                platform varchar(80) NOT NULL,
                last_contact_at timestamptz NULL,
                last_observed_at timestamptz NOT NULL,
                last_power_state text NULL,
                reported_online boolean NULL
            );
            CREATE TABLE operations.entity_observation_current (
                observation_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                entity_type varchar(80) NOT NULL,
                platform varchar(80) NOT NULL,
                active boolean NOT NULL,
                observed_at timestamptz NOT NULL,
                canonical_data jsonb NOT NULL DEFAULT '{}'
            );
            CREATE TABLE operations.sources (
                id smallint PRIMARY KEY,
                kind varchar(80) NOT NULL,
                entity_type varchar(80) NOT NULL DEFAULT ''
            );
        """)
        cur.execute(
            "INSERT INTO operations.finding_categories VALUES (1, 'data_quality')"
        )
        cur.execute(
            "INSERT INTO operations.entity_types (name, is_identity_signal) VALUES (%s, true)",
            ("vm.guest",),
        )
        cur.execute(
            """
            GRANT USAGE ON SCHEMA operations TO operations_app, ninja_ingest;
            GRANT SELECT, INSERT, UPDATE, DELETE
                ON operations.entity_types, operations.platform_aliases,
                   operations.audit_log TO operations_app;
            """
        )
        cur.execute(migration.FORWARD_SQL)
        cur.execute(
            "SELECT lifecycle_evidence_mode FROM operations.entity_types WHERE name = 'vm.guest'"
        )
        assert cur.fetchone()[0] == "none"
        # Test-only activation models the later, separately approved policy
        # migration. Production migration 0093 deliberately remains inert.
        cur.execute(
            """
            UPDATE operations.entity_types
               SET lifecycle_evidence_mode = 'reported_state'
             WHERE name = 'vm.guest'
            """
        )
        cur.execute("ALTER TABLE operations.audit_log ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE operations.audit_log FORCE ROW LEVEL SECURITY")
        cur.execute("""
            CREATE POLICY tenant_isolation ON operations.audit_log
            USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
            WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint)
        """)
        cur.execute("""
            GRANT SELECT, UPDATE ON operations.devices TO ninja_ingest;
            GRANT SELECT ON operations.device_agent_presence_current,
                operations.entity_observation_current,
                operations.entity_types TO ninja_ingest;
            GRANT SELECT, INSERT, UPDATE ON operations.findings TO ninja_ingest;
            GRANT SELECT ON operations.finding_types TO ninja_ingest;
        """)


def _set_ingest_role(cur) -> None:
    cur.execute("SET LOCAL ROLE ninja_ingest")
    cur.execute("SELECT set_config('operations.tenant_id', '1', true)")


def _set_app_role(cur) -> None:
    cur.execute("SET LOCAL ROLE operations_app")
    cur.execute("SELECT set_config('operations.tenant_id', '1', true)")


def test_track_a_postgres_permissions_rls_and_atomic_audit(postgres_connection) -> None:
    _prepare_track_a_schema(postgres_connection)
    device_id = uuid.uuid4()
    retired_device_id = uuid.uuid4()
    client_id = uuid.uuid4()
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.devices VALUES (%s, 1, %s, 'active', NULL)",
            (device_id, client_id),
        )
        cur.execute(
            "INSERT INTO operations.devices VALUES (%s, 1, %s, 'retired', NULL)",
            (retired_device_id, client_id),
        )
        cur.execute(
            """
            INSERT INTO operations.device_agent_presence_current VALUES
                (1, %s, 'vm.guest', 'Hypervisor', NULL, %s, 'poweredOff', false)
            """,
            (device_id, now),
        )
        cur.execute(
            """
            INSERT INTO operations.entity_observation_current VALUES
                (%s, 1, %s, 'vm.guest', 'Hypervisor', true, %s,
                 '{"power_state": "poweredOff"}'::jsonb)
            """,
            (uuid.uuid4(), device_id, now),
        )
        cur.execute(
            """
            INSERT INTO operations.device_agent_presence_current VALUES
                (1, %s, 'vm.guest', 'Hypervisor', NULL, %s, 'poweredOff', false)
            """,
            (retired_device_id, now),
        )

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        assert _sync_lifecycle_status(cur, 1, now, uuid.uuid4()) == 1

    with postgres_connection.cursor() as cur:
        cur.execute(
            "SELECT lifecycle_status FROM operations.devices WHERE id = %s",
            (device_id,),
        )
        assert cur.fetchone()[0] == "offline_aging"
        cur.execute("SELECT before_state, after_state FROM operations.audit_log")
        before, after = cur.fetchone()
        assert before == {"lifecycle_status": "active"}
        assert after["lifecycle_status"] == "offline_aging"
        assert after["evidence_kind"] == "reported_state"
        assert after["evidence_entity_type"] == "vm.guest"
        assert after["evidence_platform"] == "Hypervisor"
        cur.execute(
            "SELECT lifecycle_status FROM operations.devices WHERE id = %s",
            (retired_device_id,),
        )
        assert cur.fetchone()[0] == "retired"

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute("UPDATE operations.audit_log SET action = 'tampered'")

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_app_role(cur)
        cur.execute("SELECT COUNT(*) FROM operations.entity_types")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM operations.platform_aliases")
        assert cur.fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute(
                    "UPDATE operations.entity_types SET lifecycle_evidence_mode = 'none'"
                )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute(
                    "INSERT INTO operations.platform_aliases VALUES ('test', 'Test')"
                )

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_app_role(cur)
        cur.execute(
            """
            INSERT INTO operations.audit_log (
                audit_id, tenant_id, actor_kind, source, action,
                entity_type, occurred_at
            ) VALUES (gen_random_uuid(), 1, 'system', 'ui',
                      'test.append_only', 'device', NOW())
            """
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute("UPDATE operations.audit_log SET action = 'tampered'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute("DELETE FROM operations.audit_log")

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with postgres_connection.transaction():
                cur.execute(
                    """
                    INSERT INTO operations.audit_log (
                        audit_id, tenant_id, actor_kind, source, action,
                        entity_type, occurred_at
                    ) VALUES (gen_random_uuid(), 2, 'system', 'ingest',
                              'test', 'device', NOW())
                    """
                )

    with postgres_connection.cursor() as cur:
        cur.execute(
            "UPDATE operations.devices SET lifecycle_status = 'active' WHERE id = %s",
            (device_id,),
        )
        cur.execute("DELETE FROM operations.audit_log")
        cur.execute(
            """
            UPDATE operations.device_agent_presence_current
               SET last_power_state = NULL, reported_online = false
             WHERE device_id = %s
            """,
            (device_id,),
        )
        cur.execute(
            """
            UPDATE operations.entity_observation_current
               SET canonical_data = '{"power_state": null}'::jsonb
             WHERE device_id = %s
            """,
            (device_id,),
        )

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        assert _sync_lifecycle_status(cur, 1, now, uuid.uuid4()) == 1

    with postgres_connection.cursor() as cur:
        cur.execute(
            "SELECT lifecycle_status FROM operations.devices WHERE id = %s",
            (device_id,),
        )
        assert cur.fetchone()[0] == "active"
        cur.execute("SELECT COUNT(*) FROM operations.audit_log")
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            SELECT status, finding_details
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE ft.name = 'lifecycle_unknown_reported_state'
            """
        )
        status, details = cur.fetchone()
        assert status == "open"
        assert details["reported_state_kind"] == "power_state"

    with postgres_connection.cursor() as cur:
        cur.execute("UPDATE operations.findings SET status = 'investigating'")

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        assert _sync_lifecycle_status(cur, 1, now, uuid.uuid4()) == 1

    with postgres_connection.cursor() as cur:
        cur.execute("SELECT COUNT(*), MIN(status) FROM operations.findings")
        assert cur.fetchone() == (1, "investigating")
        cur.execute("UPDATE operations.findings SET status = 'suppressed'")

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        assert _sync_lifecycle_status(cur, 1, now, uuid.uuid4()) == 1

    with postgres_connection.cursor() as cur:
        cur.execute("SELECT COUNT(*), MIN(status) FROM operations.findings")
        assert cur.fetchone() == (1, "suppressed")
        cur.execute(
            """
            UPDATE operations.device_agent_presence_current
               SET last_power_state = 'poweredOn', reported_online = true
             WHERE device_id = %s
            """,
            (device_id,),
        )
        cur.execute(
            """
            UPDATE operations.entity_observation_current
               SET canonical_data = '{"power_state": "poweredOn"}'::jsonb
             WHERE device_id = %s
            """,
            (device_id,),
        )

    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        _set_ingest_role(cur)
        assert _sync_lifecycle_status(cur, 1, now, uuid.uuid4()) == 0

    with postgres_connection.cursor() as cur:
        cur.execute("SELECT status FROM operations.findings")
        assert cur.fetchone()[0] == "resolved"

    with postgres_connection.cursor() as cur:
        cur.execute(
            "UPDATE operations.devices SET lifecycle_status = 'active' WHERE id = %s",
            (device_id,),
        )
        cur.execute("DELETE FROM operations.audit_log")
        cur.execute(
            """
            UPDATE operations.device_agent_presence_current
               SET last_power_state = 'poweredOff', reported_online = false
             WHERE device_id = %s
            """,
            (device_id,),
        )
        cur.execute(
            """
            UPDATE operations.entity_observation_current
               SET canonical_data = '{"power_state": "poweredOff"}'::jsonb
             WHERE device_id = %s
            """,
            (device_id,),
        )
        cur.execute("REVOKE INSERT ON operations.audit_log FROM ninja_ingest")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with postgres_connection.transaction(), postgres_connection.cursor() as cur:
            _set_ingest_role(cur)
            _sync_lifecycle_status(cur, 1, now, uuid.uuid4())

    with postgres_connection.cursor() as cur:
        cur.execute(
            "SELECT lifecycle_status FROM operations.devices WHERE id = %s",
            (device_id,),
        )
        assert cur.fetchone()[0] == "active"
        cur.execute("SELECT COUNT(*) FROM operations.audit_log")
        assert cur.fetchone()[0] == 0
