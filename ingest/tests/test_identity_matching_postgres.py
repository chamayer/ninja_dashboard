"""Opt-in PostgreSQL coverage for the ADR-0032 matching rules.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. Column types match production
(2026-10-16). Policies are the rows migration 0307 leaves in place.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from ingest import normalize
from ingest.identity import matching
from ingest.identity.matching import IdentityMatchPolicy, resolve_match

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
POLICIES = (
    IdentityMatchPolicy(
        "source_identity", 10, False, True, False, frozenset(), Decimal("1")
    ),
    IdentityMatchPolicy(
        "serial", 20, True, False, False, frozenset({"vm_uuid"}), Decimal("1")
    ),
    IdentityMatchPolicy(
        "vm_uuid", 30, True, False, False, frozenset({"serial"}), Decimal("1")
    ),
    IdentityMatchPolicy(
        "hostname_mac",
        40,
        True,
        False,
        False,
        frozenset({"serial", "vm_uuid", "same_source_live"}),
        Decimal("0.99"),
    ),
    IdentityMatchPolicy(
        "hostname",
        50,
        True,
        False,
        False,
        frozenset({"serial", "vm_uuid", "same_source_live"}),
        Decimal("0.7"),
    ),
)

SCHEMA = """
CREATE SCHEMA operations;
CREATE TABLE operations.devices (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, client_id uuid NOT NULL,
    canonical_hostname varchar(255) NOT NULL, canonical_serial varchar(255) NOT NULL,
    lifecycle_status varchar(16) NOT NULL, deleted_at timestamptz NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY, tenant_id bigint NOT NULL, device_id uuid NULL,
    client_id uuid NULL, platform varchar(80) NOT NULL, entity_type varchar(80) NOT NULL,
    entity_key text NOT NULL, active boolean NOT NULL, last_seen_at timestamptz NOT NULL,
    canonical_data jsonb NOT NULL,
    source_instance_id uuid NOT NULL DEFAULT '00000000-0000-4000-8000-000000000010',
    external_id text NULL
);
-- Migration 0318 (production definition).
CREATE TABLE operations.identity_roaming_records (
    tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL, external_id text NOT NULL,
    platform varchar(80) NOT NULL, serial_count integer NOT NULL, name_count integer NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source_instance_id, external_id)
);
CREATE TABLE operations.device_operator_decisions (
    version integer NOT NULL, id uuid PRIMARY KEY, dimension varchar(80) NOT NULL,
    value jsonb NOT NULL, reason text NOT NULL, set_by varchar(120) NOT NULL,
    set_at timestamptz NOT NULL, tenant_id bigint NOT NULL, device_id uuid NOT NULL,
    UNIQUE (tenant_id, device_id, dimension)
);
CREATE TABLE operations.entity_types (
    name varchar(80) PRIMARY KEY, is_identity_signal boolean NOT NULL
);
INSERT INTO operations.entity_types VALUES
    ('agent.rmm', true), ('agent.remote_access', true), ('agent.edr', true),
    ('vm.guest', true), ('vm.host', true), ('cmdb.asset', false);
CREATE TABLE operations.entity_observation_history (
    tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL, external_id text NULL,
    platform varchar(80) NOT NULL, entity_type varchar(80) NOT NULL,
    material_data jsonb NOT NULL, observed_at timestamptz NOT NULL
);
-- Stand-in for the lifecycle view: no record is archived here.
CREATE TABLE operations.v_device_source_record_lifecycle_current (
    observation_id uuid PRIMARY KEY, record_lifecycle text NOT NULL
);
CREATE TABLE operations.source_name_kinds (
    platform varchar(80) NOT NULL, record_type varchar(80) NOT NULL,
    kind varchar(8) NOT NULL, rank smallint NOT NULL,
    strip_pattern text NOT NULL DEFAULT '', reason text NOT NULL DEFAULT '',
    PRIMARY KEY (platform, record_type)
);
"""


def _production_record_name_forms() -> str:
    """The function exactly as migration 0322 creates it."""
    path = (
        Path(__file__).resolve().parents[2]
        / "operations/apps/core/migrations/0322_record_names_and_shadow_naming.py"
    )
    text = path.read_text(encoding="utf-8")
    found = re.search(
        r"CREATE FUNCTION operations\.record_name_forms\(.*?\$fn\$;", text, re.S
    )
    assert found, "record_name_forms not found in migration 0322"
    return found.group(0)


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)
            connection.execute(_production_record_name_forms())
            yield connection


@pytest.fixture(autouse=True)
def _fresh_history_cache():
    matching._history_cache.clear()


@pytest.fixture(autouse=True)
def _rejections(monkeypatch):
    monkeypatch.setattr(
        normalize, "_serial_rejection_cache", frozenset({"none", "default string"})
    )


@pytest.fixture
def cur(conn):
    with conn.transaction(force_rollback=True), conn.cursor() as cursor:
        yield cursor


def computer(
    cur, name, *, serial="", created=NOW - timedelta(days=30), status="active"
):
    device_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO operations.devices VALUES (%s, 1, %s, %s, %s, %s, NULL, %s)",
        (device_id, CLIENT, name, serial, status, created),
    )
    return device_id


def record(
    cur,
    device_id,
    platform,
    *,
    active=True,
    seen=NOW,
    key=None,
    entity_type=None,
    **data,
):
    entity_key = key or str(uuid.uuid4())
    if "hostname" not in data and device_id is not None:
        # Matching reads names from records (ADR-0034); a record reports its
        # Computer's name unless the test says otherwise.
        cur.execute(
            "SELECT canonical_hostname FROM operations.devices WHERE id = %s",
            (device_id,),
        )
        data["hostname"] = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO operations.entity_observation_current
               (observation_id, tenant_id, device_id, client_id, platform, entity_type,
                entity_key, active, last_seen_at, canonical_data, external_id)
           VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            uuid.uuid4(),
            device_id,
            CLIENT,
            platform,
            entity_type
            or ("agent.rmm" if platform == "Ninja" else "agent.remote_access"),
            entity_key,
            active,
            seen,
            json.dumps(data),
            entity_key,
        ),
    )
    return entity_key


def match(
    cur,
    name=None,
    *,
    platform="LogMeIn",
    serial=None,
    vm_uuid=None,
    online=None,
    key="new",
):
    result = resolve_match(
        cur,
        tenant_id=1,
        source_name=platform,
        external_id=key,
        entity_type="agent.rmm" if platform == "Ninja" else "agent.remote_access",
        serial=serial,
        vm_uuid=vm_uuid,
        hostname=name,
        macs=[],
        client_id=CLIENT,
        policies=POLICIES,
        is_online=online,
    )
    return result.device_id if result else None


def test_a_live_computer_wins_over_an_empty_one(cur):
    computer(cur, "pc-1")  # empty leftover
    live = computer(cur, "pc-1")
    record(cur, live, "Ninja")
    assert match(cur, "pc-1") == live


def test_a_returning_machine_goes_back_to_its_empty_computer(cur):
    empty = computer(cur, "pc-2")
    record(cur, empty, "Ninja", active=False, serial_number="ABC123")
    assert match(cur, "pc-2") == empty
    # A replacement machine reusing the name has a different serial.
    assert match(cur, "pc-2", serial="XYZ999") is None


def test_serial_is_compared_with_what_records_report_now(cur):
    stale = computer(cur, "gf-12", serial="OLD123")
    record(cur, stale, "Ninja", serial_number="NEW456")
    # The old laptop, renamed, still reports the stored serial: no match.
    assert match(cur, "gf-32", platform="SentinelOne", serial="OLD123") is None
    assert match(cur, "anything", platform="SentinelOne", serial="new456") == stale


def test_a_different_serial_blocks_a_name_match(cur):
    laptop = computer(cur, "laptop11")
    record(cur, laptop, "Ninja", serial_number="R90Y8E9Q")
    assert match(cur, "laptop11", platform="ScreenConnect", serial="PF12JB52") is None
    assert match(cur, "laptop11", platform="ScreenConnect") == laptop


def test_two_live_records_of_one_source_are_two_machines(cur):
    server = computer(cur, "server")
    record(cur, server, "LogMeIn", is_online=True)
    assert match(cur, "server", online=True) is None
    # A re-registration while the old entry is offline is the same machine.
    assert match(cur, "server", online=False) == server


def test_several_candidates_pick_the_most_recently_active(cur):
    older = computer(cur, "dev-sql2", created=NOW - timedelta(days=90))
    newer = computer(cur, "dev-sql2", created=NOW - timedelta(days=10))
    record(cur, older, "Ninja", seen=NOW - timedelta(days=5))
    record(cur, newer, "SentinelOne", seen=NOW - timedelta(hours=1))
    assert match(cur, "dev-sql2") == newer


def test_a_15_character_cut_matches_one_longer_name(cur):
    full = computer(cur, "adh-sp-rdapps-test")
    record(cur, full, "SentinelOne")
    assert match(cur, "adh-sp-rdapps-t", platform="Ninja") == full
    a = computer(cur, "abcdefghijklmno1")
    b = computer(cur, "abcdefghijklmno2")
    record(cur, a, "SentinelOne")
    record(cur, b, "SentinelOne")
    assert match(cur, "abcdefghijklmno", platform="Ninja") is None


def test_separator_variants_match(cur):
    qb = computer(cur, "qb-server")
    record(cur, qb, "Ninja")
    assert match(cur, "qbserver", platform="R-U-ON") == qb


def test_duplicate_agents_on_one_serial_share_a_computer(cur):
    pc = computer(cur, "pc-9")
    record(cur, pc, "SentinelOne", serial_number="GM13HWMH", is_online=True)
    assert (
        match(cur, "pc-9", platform="SentinelOne", serial="GM13HWMH", online=True) == pc
    )


def test_a_record_split_off_never_returns_to_that_computer(cur):
    pc = computer(cur, "pc-split")
    record(cur, pc, "Ninja")
    cur.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, %s, 'identity_excluded_records', '["LogMeIn|lmi-7"]', 'two machines',
                   'user:7', now(), 1, %s)""",
        (uuid.uuid4(), pc),
    )
    assert match(cur, "pc-split", key="lmi-7") is None
    assert match(cur, "pc-split", key="lmi-8") == pc


def _roam(cur, key):
    cur.execute(
        """INSERT INTO operations.identity_roaming_records
               (tenant_id, source_instance_id, external_id, platform, serial_count, name_count)
           VALUES (1, '00000000-0000-4000-8000-000000000010', %s, 'SentinelOne', 5, 5)""",
        (key,),
    )


def test_a_roaming_record_proves_nothing_by_serial(cur):
    """An image agent moving between clones (migration 0318)."""
    clone = computer(cur, "citrixapp37")
    image = computer(cur, "citrixappmcs")
    record(cur, clone, "Ninja", serial_number="VMW-37")
    roaming = record(cur, image, "SentinelOne", serial_number="VMW-37")
    _roam(cur, roaming)
    # As a candidate: its serial does not pull another record to its Computer.
    assert match(cur, "other-name", platform="ScreenConnect", serial="vmw-37") == clone
    # As the incoming record: it is placed by name, not by the clone's serial.
    assert (
        match(cur, "citrixappmcs", platform="SentinelOne", serial="VMW-37", key=roaming)
        == image
    )


def test_placeholder_serials_never_match(cur):
    pc = computer(cur, "ws-1")
    record(cur, pc, "Ninja", serial_number="Default string")
    assert match(cur, "other", platform="SentinelOne", serial="Default string") is None
