"""Migration 0308 on a real PostgreSQL: merge, split, and the merge-relation guard.

Tables use production column types and NOT NULL definitions (2026-10-16);
0306's foundation runs first so merges are recorded in the change history.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA

TABLES = """
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY, tenant_id bigint NOT NULL, device_id uuid NULL,
    platform varchar(80) NOT NULL, entity_key text NOT NULL, active boolean NOT NULL,
    canonical_data jsonb NOT NULL
);
CREATE TABLE operations.findings (
    version integer NOT NULL, id uuid PRIMARY KEY, subject_type varchar(32) NOT NULL,
    subject_id uuid NOT NULL, finding_details jsonb NOT NULL, severity varchar(16) NOT NULL,
    status varchar(24) NOT NULL, first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL, finding_type_id smallint NOT NULL,
    tenant_id bigint NOT NULL, client_id uuid NULL, condition_key varchar(255) NOT NULL,
    confidence varchar(16) NOT NULL, subject_layer varchar(16) NOT NULL
);
CREATE TABLE operations.condition_participants (
    tenant_id bigint NOT NULL, row_kind text NOT NULL, finding_id uuid NOT NULL,
    participant_kind text NOT NULL, participant_id uuid NOT NULL, participant_role text NOT NULL,
    PRIMARY KEY (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
);
CREATE TABLE operations.condition_assessments (
    tenant_id bigint NOT NULL, row_kind text NOT NULL, finding_id uuid NOT NULL,
    participant_kind text NOT NULL, participant_id uuid NOT NULL, participant_role text NOT NULL,
    condition_identity text NOT NULL, policy_version text NOT NULL, coverage jsonb NOT NULL,
    response jsonb NOT NULL, reevaluation_key text NOT NULL, assessed_at timestamptz NOT NULL,
    policy_digest text NOT NULL, currentness jsonb NOT NULL,
    PRIMARY KEY (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
);
CREATE TABLE operations.software_installations_current (
    tenant_id bigint NOT NULL, client_id uuid NOT NULL, device_id uuid NOT NULL,
    canonical_name text NOT NULL, publisher text NULL, version text NULL,
    install_location text NULL, install_date date NULL,
    first_observed_at timestamptz NOT NULL, last_observed_at timestamptz NOT NULL,
    refreshed_at timestamptz NOT NULL,
    installation_uuid uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    PRIMARY KEY (tenant_id, client_id, device_id, canonical_name)
);
"""

CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(FOUNDATION_SCHEMA)
            connection.execute(TABLES)
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            module = importlib.import_module("apps.core.migrations.0308_computer_merge_and_split")
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def _computer(conn, name, client=CLIENT):
    device_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.devices VALUES (1, %s, %s, '', '', 'unknown', NULL, %s, 1,
               now(), 'test', now(), '', NULL, '', '', 'workstation', '', '', 'active',
               'Windows', %s)""",
        (device_id, name, client, device_id),
    )
    return device_id


def _observation(conn, device_id, platform):
    observation_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.entity_observation_current VALUES (%s, 1, %s, %s, %s, true, '{}')",
        (observation_id, device_id, platform, str(uuid.uuid4())),
    )
    return observation_id


def _finding(conn, device_id):
    finding_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.findings VALUES (1, %s, 'device', %s, '{}', 'high', 'open',
               now(), now(), 14, 1, %s, %s, 'probable', '')""",
        (finding_id, device_id, CLIENT, str(uuid.uuid4())),
    )
    return finding_id


def test_merge_moves_everything_and_split_restores_only_the_merged_memberships(conn):
    survivor, absorbed = _computer(conn, "pc-1"), _computer(conn, "pc-1")
    kept_obs = _observation(conn, survivor, "Ninja")
    moved_obs = _observation(conn, absorbed, "SentinelOne")
    moved_finding = _finding(conn, absorbed)
    conn.execute(
        """INSERT INTO operations.software_installations_current
               (tenant_id, client_id, device_id, canonical_name, version, first_observed_at,
                last_observed_at, refreshed_at)
           VALUES (1, %s, %s, 'chrome', '120', now() - interval '2 days', now() - interval '1 day', now()),
                  (1, %s, %s, 'chrome', '121', now() - interval '3 days', now(), now()),
                  (1, %s, %s, 'zoom', '5', now(), now(), now())""",
        (CLIENT, survivor, CLIENT, absorbed, CLIENT, absorbed),
    )

    with conn.transaction():
        merge_id = conn.execute(
            """SELECT operations.merge_computers(%s, %s, 'same serial on both',
                   %s::jsonb, 'process', NULL, 'ingest.resolver')""",
            (survivor, absorbed, json.dumps({"serial": "abc123"})),
        ).fetchone()[0]

    assert (
        conn.execute(
            "SELECT count(*) FROM operations.entity_observation_current WHERE device_id = %s",
            (survivor,),
        ).fetchone()[0]
        == 2
    )
    details = conn.execute(
        "SELECT subject_id, finding_details FROM operations.findings WHERE id = %s",
        (moved_finding,),
    ).fetchone()
    assert details[0] == survivor
    assert details[1]["merge"]["from_device_id"] == str(absorbed)
    software = dict(
        conn.execute(
            "SELECT canonical_name, version FROM operations.software_installations_current WHERE device_id = %s",
            (survivor,),
        ).fetchall()
    )
    assert software == {"chrome": "121", "zoom": "5"}
    assert (
        conn.execute(
            "SELECT deleted_reason FROM operations.devices WHERE id = %s", (absorbed,)
        ).fetchone()[0]
        == "merged"
    )
    action = conn.execute(
        """SELECT a.action, a.explicit FROM operations.computer_merges m
             JOIN operations.change_actions a ON a.id = m.action_id WHERE m.id = %s""",
        (merge_id,),
    ).fetchone()
    assert action == ("computer.merge.automatic", True)

    # Later history on the survivor: a new finding after the merge stays put.
    later_finding = _finding(conn, survivor)

    with conn.transaction():
        conn.execute(
            "SELECT operations.split_computer_merge(%s, 'two machines after all', 'operator', 7, 'ui')",
            (merge_id,),
        )
    assert (
        conn.execute(
            "SELECT device_id FROM operations.entity_observation_current WHERE observation_id = %s",
            (moved_obs,),
        ).fetchone()[0]
        == absorbed
    )
    assert (
        conn.execute(
            "SELECT device_id FROM operations.entity_observation_current WHERE observation_id = %s",
            (kept_obs,),
        ).fetchone()[0]
        == survivor
    )
    assert (
        conn.execute(
            "SELECT subject_id FROM operations.findings WHERE id = %s", (moved_finding,)
        ).fetchone()[0]
        == absorbed
    )
    assert (
        conn.execute(
            "SELECT subject_id FROM operations.findings WHERE id = %s", (later_finding,)
        ).fetchone()[0]
        == survivor
    )
    assert conn.execute(
        "SELECT deleted_at IS NULL FROM operations.devices WHERE id = %s", (absorbed,)
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("SELECT operations.split_computer_merge(%s, 'again')", (merge_id,))


def test_a_merged_tombstone_needs_a_merge_relation(conn):
    lone = _computer(conn, "pc-2")
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute(
            "UPDATE operations.devices SET deleted_at = now(), deleted_reason = 'merged' WHERE id = %s",
            (lone,),
        )


def test_computers_of_different_clients_are_never_merged(conn):
    a = _computer(conn, "pc-3")
    b = _computer(conn, "pc-3", client=uuid.uuid4())
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("SELECT operations.merge_computers(%s, %s, 'x')", (a, b))


def test_runtime_roles_can_merge_but_not_split_from_ingest(conn):
    a, b = _computer(conn, "pc-4"), _computer(conn, "pc-4")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        merge_id = conn.execute(
            "SELECT operations.merge_computers(%s, %s, 'same serial')", (a, b)
        ).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT operations.split_computer_merge(%s, 'x')", (merge_id,))
