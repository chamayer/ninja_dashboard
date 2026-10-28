"""Per-record evidence stays distinct on Computer and merge-review pages."""

from __future__ import annotations

import importlib
import os
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest
from django.template.loader import get_template
from django.utils import timezone as django_timezone
from psycopg.types.json import Jsonb

from apps.core.views import _device_source_records

MIGRATION = "apps.core.migrations.0361_source_record_reported_contact"
COMPUTER = uuid.UUID("00000000-0000-4000-8000-000000000001")
COLLECTED = datetime(2026, 10, 28, 20, tzinfo=UTC)
SCHEMA = """
CREATE ROLE operations_view_owner NOLOGIN BYPASSRLS;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE SCHEMA operations;
GRANT USAGE ON SCHEMA operations TO operations_view_owner, operations_app,
    operations_readonly, ninja_ingest;
GRANT CREATE ON SCHEMA operations TO operations_view_owner;
CREATE FUNCTION operations.current_tenant_id() RETURNS bigint LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('operations.tenant_id', true), '')::bigint
$$;
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
    source_binding_id uuid, source_instance_id uuid, client_id uuid, device_id uuid,
    entity_type text DEFAULT 'agent.remote_access', entity_key text,
    external_namespace text DEFAULT 'access-session', parent_external_namespace text DEFAULT '',
    parent_external_id text DEFAULT '', external_id text, platform text DEFAULT 'ScreenConnect',
    subplatform text DEFAULT '', observed_at timestamptz, last_seen_at timestamptz,
    last_received_at timestamptz, active boolean DEFAULT true, withdrawn_at timestamptz,
    canonical_data jsonb NOT NULL DEFAULT '{}', raw_data jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE operations.evaluator_config (
    tenant_id bigint, evaluator_name text, config jsonb
);
GRANT SELECT ON ALL TABLES IN SCHEMA operations TO operations_view_owner;
ALTER TABLE operations.entity_observation_current ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON operations.entity_observation_current
    USING (tenant_id = operations.current_tenant_id());
INSERT INTO operations.evaluator_config VALUES
    (1, 'restricted_source_layouts', '{"layouts": {"private-layout": true}}');
"""
READ_MODELS = """
CREATE VIEW operations.v_device_observation_current AS
    SELECT device_id, tenant_id, observation_id, platform AS source_name,
           entity_type, external_id, active AS observation_active,
           last_seen_at AS observation_last_seen_at
      FROM operations.v_entity_observation_admin_metadata;
CREATE VIEW operations.v_device_source_record_lifecycle_current AS
    SELECT tenant_id, observation_id, 'unknown'::text AS record_lifecycle
      FROM operations.v_entity_observation_admin_metadata;
CREATE VIEW operations.v_cmdb_inventory_evidence_current AS
    SELECT tenant_id, observation_id, 'Hudu'::text AS source_name, NULL::text AS source_url
      FROM operations.v_entity_observation_admin_metadata WHERE false;
-- Deliberately contradictory platform state: the old reader copied this to every row.
CREATE TABLE operations.device_agent_presence_current (
    tenant_id bigint, device_id uuid, platform text, entity_type text,
    reported_online boolean, last_contact_at timestamptz, last_observed_at timestamptz
);
INSERT INTO operations.device_agent_presence_current VALUES
    (1, '00000000-0000-4000-8000-000000000001', 'ScreenConnect',
     'agent.remote_access', true, '2026-10-28T19:00:00Z', '2026-10-28T20:00:00Z');
GRANT SELECT ON operations.v_device_observation_current,
    operations.v_device_source_record_lifecycle_current,
    operations.v_cmdb_inventory_evidence_current,
    operations.device_agent_presence_current TO operations_app, operations_readonly;
"""


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for disposable PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(SCHEMA)
            previous = importlib.import_module(
                "apps.core.migrations.0360_source_record_reported_state"
            )
            conn.execute(previous.FORWARD_SQL)
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='operations' AND table_name='v_entity_observation_admin_metadata' "
                "ORDER BY ordinal_position"
            ).fetchall()
            conn.execute(importlib.import_module(MIGRATION).FORWARD_SQL)
            conn.execute(READ_MODELS)
            yield conn, columns


@pytest.fixture
def cur(database):
    with database[0].transaction(force_rollback=True), database[0].cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = '1'")
        yield cursor


def _insert(cur, external_id, *, online=False, contact=None, tenant=1, active=True, **extra):
    observation_id = uuid.uuid4()
    cur.execute(
        """INSERT INTO operations.entity_observation_current
           (observation_id, tenant_id, device_id, entity_key, external_id,
            observed_at, last_seen_at, last_received_at, active, canonical_data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            observation_id,
            tenant,
            COMPUTER,
            external_id,
            external_id,
            COLLECTED,
            COLLECTED,
            COLLECTED,
            active,
            Jsonb({"is_online": online, "last_seen_at": contact, **extra}),
        ),
    )
    return observation_id


@pytest.mark.parametrize("role", ["operations_app", "operations_readonly"])
def test_each_session_keeps_its_own_state_and_contact(cur, role):
    _insert(cur, "older-session", contact="2026-01-02T03:04:00Z")
    _insert(cur, "newer-session", online=True, contact="2026-10-28T18:30:00+00:00")
    _insert(cur, "unknown-session", online=None)
    _insert(cur, "withdrawn-session", contact="2026-03-04T05:06:00Z", active=False)
    cur.execute(f"SET LOCAL ROLE {role}")
    rows = {row[3]: row for row in _device_source_records(cur, [COMPUTER])[str(COMPUTER)]}
    assert rows["older-session"][7:9] == (
        False,
        datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
    )
    assert rows["newer-session"][7:9] == (
        True,
        datetime(2026, 10, 28, 18, 30, tzinfo=UTC),
    )
    assert rows["unknown-session"][7:9] == (None, None)
    assert rows["withdrawn-session"][5] is False
    assert rows["withdrawn-session"][8] == datetime(2026, 3, 4, 5, 6, tzinfo=UTC)
    assert all(row[6] == COLLECTED for row in rows.values())


@pytest.mark.parametrize(
    "contact",
    [
        None,
        "",
        "not-a-date",
        "infinity",
        "-infinity",
        "0001-01-01T00:00:00Z",
        "2026-13-28T18:30:00Z",
        "2026-02-30T18:30:00Z",
        "2026-10-28T18:30:00",
        "2026-10-28",
        {"unexpected": "object"},
        123,
    ],
)
def test_invalid_or_unmeasurable_contact_does_not_borrow_collection_time(cur, contact):
    _insert(cur, "unmeasurable-session", contact=contact)
    cur.execute("SET LOCAL ROLE operations_app")
    row = _device_source_records(cur, [COMPUTER])[str(COMPUTER)][0]
    assert row[6] == COLLECTED
    assert row[8] is None


def test_offset_contact_is_an_instant_and_does_not_use_session_timezone(cur):
    _insert(cur, "offset-session", contact="2026-10-28T14:30:00.123456-04:00")
    cur.execute("SET LOCAL TIME ZONE 'Asia/Tokyo'")
    cur.execute("SET LOCAL ROLE operations_app")
    row = _device_source_records(cur, [COMPUTER])[str(COMPUTER)][0]
    assert row[8] == datetime(2026, 10, 28, 18, 30, 0, 123456, tzinfo=UTC)


def test_restricted_layout_masks_both_status_and_contact(cur):
    _insert(
        cur,
        "restricted-session",
        online=True,
        contact="2026-10-28T18:30:00Z",
        source_layout="private-layout",
    )
    cur.execute("SET LOCAL ROLE operations_app")
    row = _device_source_records(cur, [COMPUTER])[str(COMPUTER)][0]
    assert row[7:9] == (None, None)


def test_runtime_tenant_filter_does_not_expose_other_tenants(cur):
    _insert(cur, "tenant-one")
    _insert(cur, "tenant-two", tenant=2, online=True)
    cur.execute("SET LOCAL ROLE operations_app")
    rows = _device_source_records(cur, [COMPUTER])[str(COMPUTER)]
    assert [row[3] for row in rows] == ["tenant-one"]
    cur.execute("SET LOCAL operations.tenant_id = '2'")
    assert _device_source_records(cur, [COMPUTER]) == {}
    cur.execute("SELECT external_id FROM operations.v_entity_observation_admin_metadata")
    assert cur.fetchall() == [("tenant-two",)]


def test_additive_migration_keeps_columns_security_barrier_and_runtime_privileges(cur, database):
    # Exercise explicit revocation even if a deployment inherited default DML grants.
    cur.execute(
        "GRANT INSERT, UPDATE, DELETE, TRUNCATE ON "
        "operations.v_entity_observation_admin_metadata TO operations_app, operations_readonly"
    )
    cur.execute(importlib.import_module(MIGRATION).FORWARD_SQL)
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='operations' AND table_name='v_entity_observation_admin_metadata' "
        "ORDER BY ordinal_position"
    )
    assert cur.fetchall() == [*database[1], ("reported_last_contact_at",)]
    cur.execute(
        "SELECT reloptions FROM pg_class WHERE oid="
        "'operations.v_entity_observation_admin_metadata'::regclass"
    )
    assert "security_barrier=true" in cur.fetchone()[0]
    for role in ("operations_app", "operations_readonly"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cur.execute(
                "SELECT has_table_privilege(%s, "
                "'operations.v_entity_observation_admin_metadata', %s)",
                (role, privilege),
            )
            assert cur.fetchone()[0] is (privilege == "SELECT")
        cur.execute(
            "SELECT has_table_privilege(%s, " "'operations.entity_observation_current', 'SELECT')",
            (role,),
        )
        assert cur.fetchone()[0] is False


@pytest.mark.parametrize("template_name", ["device_detail.html", "_merge_source_records.html"])
def test_pages_render_distinct_session_states_and_contact_times(cur, template_name, monkeypatch):
    # The finding-label registry is unrelated to source-record evidence.
    monkeypatch.setattr("apps.core.finding_registry._load_names", lambda: {})
    _insert(cur, "older-session", contact="2026-01-02T03:04:00Z")
    _insert(cur, "newer-session", online=True, contact="2026-10-28T18:30:00Z")
    _insert(cur, "unknown-session", online=None)
    cur.execute("SET LOCAL ROLE operations_app")
    rows = _device_source_records(cur, [COMPUTER])[str(COMPUTER)]
    device = SimpleNamespace(
        id=COMPUTER,
        entity_id=COMPUTER,
        canonical_hostname="Synthetic Computer",
        client=SimpleNamespace(slug="synthetic-client", display_name="Synthetic Client"),
        source_status_rows=rows,
    )
    with django_timezone.override("UTC"):
        html = get_template(template_name).render(
            {
                "device": device,
                "observations": [(*row, []) for row in rows],
                "active_tab": "details",
            }
        )
    rendered_rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.DOTALL)
    older = next(row for row in rendered_rows if "older-session" in row)
    newer = next(row for row in rendered_rows if "newer-session" in row)
    unknown = next(row for row in rendered_rows if "unknown-session" in row)
    assert ">Offline<" in older and "2026-01-02 03:04" in older
    assert ">Online<" in newer and "2026-10-28 18:30" in newer
    assert "Not reported" in unknown and "—" in unknown
    assert "2026-10-28 20:00" in older and "2026-10-28 20:00" in newer
