"""Migration 0306 on a real PostgreSQL: change history is recorded, scoped and enforceable.

Tables are created with production column types (read from production
2026-10-16) and the migration's SQL runs as ``operations_migrate``.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

MODULE = "apps.core.migrations.0306_change_history_foundation"

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN SUPERUSER;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE SCHEMA operations AUTHORIZATION operations_migrate;
GRANT USAGE ON SCHEMA operations TO operations_app, operations_readonly, ninja_ingest;
CREATE TABLE operations.devices (
    version integer NOT NULL, id uuid PRIMARY KEY,
    canonical_hostname varchar(255) NOT NULL, canonical_serial varchar(255) NOT NULL,
    canonical_vm_uuid varchar(64) NOT NULL, device_type varchar(32) NOT NULL,
    deleted_at timestamptz NULL, client_id uuid NOT NULL, tenant_id bigint NOT NULL,
    created_at timestamptz NOT NULL, created_reason varchar(120) NOT NULL,
    updated_at timestamptz NOT NULL, updated_reason varchar(120) NOT NULL,
    stale_since timestamptz NULL, stale_reason varchar(120) NOT NULL,
    deleted_reason varchar(120) NOT NULL, device_role varchar(16) NOT NULL,
    os_name varchar(200) NOT NULL, os_family varchar(40) NOT NULL,
    lifecycle_status varchar(16) NOT NULL, os_group varchar(16) NOT NULL, entity_id uuid NOT NULL
);
CREATE TABLE operations.users (
    id bigint PRIMARY KEY, password varchar(128) NOT NULL, last_login timestamptz NULL,
    is_superuser boolean NOT NULL, username varchar(150) NOT NULL, first_name varchar(150) NOT NULL,
    last_name varchar(150) NOT NULL, email varchar(254) NOT NULL, is_staff boolean NOT NULL,
    is_active boolean NOT NULL, date_joined timestamptz NOT NULL, timezone varchar(64) NOT NULL,
    tenant_id bigint NOT NULL
);
CREATE TABLE operations.cve_match (
    id bigint PRIMARY KEY, tenant_id bigint NOT NULL, canonical_name text NOT NULL,
    cve_id text NOT NULL, match_kind text NOT NULL, version_range text NULL,
    confidence text NOT NULL, matched_at timestamptz NOT NULL, software_version_id bigint NULL
);
ALTER TABLE operations.devices OWNER TO operations_migrate;
ALTER TABLE operations.users OWNER TO operations_migrate;
ALTER TABLE operations.cve_match OWNER TO operations_migrate;
ALTER TABLE operations.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.devices FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.devices
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.devices TO ninja_ingest, operations_app;
GRANT SELECT, INSERT, UPDATE ON operations.users TO operations_app;
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
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(module.FOUNDATION_SQL)
            yield connection


def _device(conn, device_id, client_id, **overrides):
    values = {
        "version": 1,
        "id": device_id,
        "canonical_hostname": "pc-1",
        "canonical_serial": "",
        "canonical_vm_uuid": "",
        "device_type": "unknown",
        "client_id": client_id,
        "tenant_id": 1,
        "created_reason": "test",
        "updated_reason": "",
        "stale_reason": "",
        "deleted_reason": "",
        "device_role": "workstation",
        "os_name": "",
        "os_family": "",
        "lifecycle_status": "active",
        "os_group": "Windows",
        "entity_id": device_id,
    } | overrides
    conn.execute(
        """
        INSERT INTO operations.devices (version, id, canonical_hostname, canonical_serial,
            canonical_vm_uuid, device_type, client_id, tenant_id, created_at, created_reason,
            updated_at, updated_reason, stale_reason, deleted_reason, device_role, os_name,
            os_family, lifecycle_status, os_group, entity_id)
        VALUES (%(version)s, %(id)s, %(canonical_hostname)s, %(canonical_serial)s,
            %(canonical_vm_uuid)s, %(device_type)s, %(client_id)s, %(tenant_id)s, now(),
            %(created_reason)s, now(), %(updated_reason)s, %(stale_reason)s, %(deleted_reason)s,
            %(device_role)s, %(os_name)s, %(os_family)s, %(lifecycle_status)s, %(os_group)s,
            %(entity_id)s)
        """,
        values,
    )


def _history(conn, table, key):
    return conn.execute(
        f"""SELECT h.operation, h.changed_columns, h.before_values, h.after_values,
                   h.computer_id, h.client_id, h.tenant_id, a.action, a.explicit, a.process
              FROM operations.{table}_change_history h
              JOIN operations.change_actions a ON a.id = h.action_id
             WHERE h.entity_key = %s ORDER BY h.id""",
        (key,),
    ).fetchall()


def test_every_production_table_is_classified_and_covered_ones_get_history(conn):
    counts = dict(
        conn.execute(
            "SELECT classification, count(*) FROM operations.change_history_registry GROUP BY 1"
        ).fetchall()
    )
    assert sum(counts.values()) == 155
    assert counts["covered"] == 78
    for table in ("devices", "users", "cve_match"):
        assert conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (f"operations.{table}_change_history",)
        ).fetchone()[0]
    # cve_match is written by the matcher, not by a row trigger.
    triggers = dict(
        conn.execute(
            """SELECT c.relname, count(t.*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                WHERE t.tgname = 'record_change' GROUP BY 1"""
        ).fetchall()
    )
    assert triggers == {"devices": 1, "users": 1}


def test_a_runtime_writer_records_meaningful_changes_only(conn):
    device_id, client_id = uuid.uuid4(), uuid.uuid4()
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        _device(conn, device_id, client_id)
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        # Only bookkeeping columns change: nothing is recorded.
        conn.execute(
            "UPDATE operations.devices SET updated_at = now(), version = version + 1 WHERE id = %s",
            (device_id,),
        )
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        conn.execute(
            "UPDATE operations.devices SET canonical_hostname = 'pc-2' WHERE id = %s", (device_id,)
        )

    rows = _history(conn, "devices", str(device_id))
    assert [r[0] for r in rows] == ["I", "U"]
    op, changed, before, after, computer, client, tenant, action, explicit, process = rows[1]
    assert changed == ["canonical_hostname"]
    assert before["canonical_hostname"] == "pc-1" and after["canonical_hostname"] == "pc-2"
    assert "updated_at" not in after and "version" not in after
    assert (computer, client, tenant) == (device_id, client_id, 1)
    assert (action, explicit) == ("implicit", False)
    assert process.startswith("ninja_ingest")


def test_one_explicit_action_groups_its_changes(conn):
    first, second, client_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        action_id = conn.execute(
            """SELECT operations.begin_change('computer.merge', 'test merge',
                   '{"matched": "serial"}'::jsonb, 'operator', 7, 'operations.ui')"""
        ).fetchone()[0]
        _device(conn, first, client_id)
        _device(conn, second, client_id)
    actions = {
        r[0]
        for r in conn.execute(
            "SELECT action_id FROM operations.devices_change_history WHERE entity_key = ANY(%s)",
            ([str(first), str(second)],),
        ).fetchall()
    }
    assert actions == {action_id}
    row = conn.execute(
        "SELECT action, reason, actor_kind, actor_id, explicit, evidence FROM operations.change_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row == ("computer.merge", "test merge", "operator", 7, True, {"matched": "serial"})


def test_secret_values_are_never_stored(conn):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        conn.execute(
            """INSERT INTO operations.users VALUES (42, 'pbkdf2$secret-hash', NULL, false, 'amy',
                   'Amy', 'B', 'amy@example.test', false, true, now(), 'UTC', 1)"""
        )
        conn.execute("UPDATE operations.users SET password = 'pbkdf2$other' WHERE id = 42")
        conn.execute("UPDATE operations.users SET last_login = now() WHERE id = 42")
    rows = _history(conn, "users", "42")
    assert [r[0] for r in rows] == ["I", "U"]  # the last_login update is bookkeeping
    assert rows[1][1] == ["password"]
    assert rows[1][2]["password"] == "[secret]" and rows[1][3]["password"] == "[secret]"
    dump = str(
        conn.execute("SELECT json_agg(h) FROM operations.users_change_history h").fetchone()[0]
    )
    assert "secret-hash" not in dump and "pbkdf2$other" not in dump


def test_history_is_append_only_and_tenant_scoped_for_runtime_roles(conn):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        assert (
            conn.execute("SELECT count(*) FROM operations.devices_change_history").fetchone()[0] > 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("DELETE FROM operations.devices_change_history")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "INSERT INTO operations.change_actions (action, actor_kind, explicit) VALUES ('x', 'system', true)"
            )
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '2', true)")
        assert (
            conn.execute("SELECT count(*) FROM operations.devices_change_history").fetchone()[0]
            == 0
        )


def test_enforced_tables_reject_changes_without_an_action(conn):
    conn.execute(
        "UPDATE operations.change_history_registry SET enforce_action = true WHERE table_name = 'devices'"
    )
    try:
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
            _device(conn, uuid.uuid4(), uuid.uuid4())
        with conn.transaction():
            conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
            conn.execute("SELECT operations.begin_change('test.enforced')")
            _device(conn, uuid.uuid4(), uuid.uuid4())
    finally:
        conn.execute(
            "UPDATE operations.change_history_registry SET enforce_action = false WHERE table_name = 'devices'"
        )


def test_cve_match_records_only_real_differences(conn):
    conn.execute(
        """INSERT INTO operations.cve_match VALUES
             (1, 1, 'chrome', 'CVE-1', 'cpe_exact', '*', 'high', now(), NULL),
             (2, 1, 'chrome', 'CVE-2', 'cpe_exact', '*', 'high', now(), NULL)"""
    )
    with conn.transaction():
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        conn.execute(
            """CREATE TEMP TABLE cve_match_before ON COMMIT DROP AS
               SELECT canonical_name, software_version_id, cve_id, match_kind, version_range,
                      confidence FROM operations.cve_match WHERE tenant_id = 1"""
        )
        conn.execute("DELETE FROM operations.cve_match WHERE tenant_id = 1")
        conn.execute(
            """INSERT INTO operations.cve_match VALUES
                 (3, 1, 'chrome', 'CVE-2', 'cpe_exact', '*', 'high', now(), NULL),
                 (4, 1, 'chrome', 'CVE-3', 'cpe_exact', '*', 'high', now(), NULL)"""
        )
        conn.execute("SET LOCAL ROLE ninja_ingest")
        assert conn.execute("SELECT operations.record_cve_match_changes(1)").fetchone()[0] == 2
    rows = conn.execute(
        """SELECT h.entity_key, h.operation, a.action FROM operations.cve_match_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id ORDER BY h.entity_key"""
    ).fetchall()
    assert rows == [
        ("chrome||CVE-1", "D", "cve_match.refresh"),
        ("chrome||CVE-3", "I", "cve_match.refresh"),
    ]


def test_a_new_table_shows_as_unclassified(conn):
    assert conn.execute("SELECT * FROM operations.change_history_unclassified()").fetchall() == []
    conn.execute("CREATE TABLE operations.brand_new_table (id int PRIMARY KEY)")
    try:
        assert conn.execute(
            "SELECT * FROM operations.change_history_unclassified()"
        ).fetchall() == [("brand_new_table",)]
    finally:
        conn.execute("DROP TABLE operations.brand_new_table")


def test_policy_adds_the_new_type_once():
    module = importlib.import_module(MODULE)
    active = {
        "version": "conditions-registry-1",
        "schema_version": 2,
        "rules": {},
        "freshness_hours": 2,
        "definitions": [{"name": "a", "rules": [], "lifecycle": "active"}],
    }
    policy = module.build_policy(active)
    assert policy["version"] == "conditions-registry-2"
    assert [d["name"] for d in policy["definitions"]] == ["a", "change_history_unclassified"]
    assert module.build_policy(policy)["definitions"] == policy["definitions"]
