"""Migration 0318 on a real PostgreSQL: roaming agent records, and the merge they caused.

Every statement runs against production definitions (2026-10-18): the
observation history the list is computed from, the merge tables of 0308 /
0315 / 0317 for the split, and 0306's registry the table is classified in.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer
from apps.core.tests.test_migration_0315_postgres import LINKS

HISTORY = """
ALTER TABLE operations.entity_observation_current
    ADD COLUMN source_instance_id uuid NOT NULL DEFAULT '00000000-0000-4000-8000-000000000020',
    ADD COLUMN external_id text NOT NULL DEFAULT '',
    ADD COLUMN entity_type varchar(80) NOT NULL DEFAULT 'agent.edr',
    ADD COLUMN last_seen_at timestamptz NULL;
CREATE TABLE operations.entity_observation_history (
    id uuid PRIMARY KEY, entity_type varchar(80) NOT NULL, entity_key text NOT NULL,
    effective_from timestamptz NOT NULL, material_data jsonb NOT NULL,
    tenant_id bigint NOT NULL, platform varchar(80) NOT NULL,
    source_instance_id uuid NOT NULL, external_id text NOT NULL
);
"""
SOURCE = uuid.UUID("00000000-0000-4000-8000-000000000020")
START = datetime(2026, 9, 1, tzinfo=UTC)


def _versions(conn, key, rows):
    for i, (name, serial) in enumerate(rows):
        conn.execute(
            """INSERT INTO operations.entity_observation_history
               VALUES (%s, 'agent.edr', %s, %s, %s::jsonb, 1, 'SentinelOne', %s, %s)""",
            (uuid.uuid4(), key, START + timedelta(days=i),
             json.dumps({"hostname": name, "serial_number": serial}), SOURCE, key),
        )


def _record(conn, device, key):
    observation = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.entity_observation_current
               (observation_id, tenant_id, device_id, platform, entity_key, active,
                canonical_data, source_instance_id, external_id)
           VALUES (%s, 1, %s, 'SentinelOne', %s, true, '{}', %s, %s)""",
        (observation, device, key, SOURCE, key),
    )
    return observation


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
            connection.execute(LINKS)
            connection.execute(HISTORY)
            # An image agent moving between clones, a real rename with a hardware
            # change, and filler serials.
            _versions(connection, "s1-image", [("CitrixAppMCS", "VMW-1"), ("CitrixApp29", "VMW-2"),
                                               ("CitrixApp33", "VMW-3"), ("CitrixApp27", "VMW-4")])
            _versions(connection, "s1-rename", [("DEL-LP12", "SN-A"), ("DEL-LP09", "SN-B")])
            _versions(connection, "s1-filler", [("PC-1", "None"), ("PC-2", ""), ("PC-3", "abc")])
            for name in ("0306_change_history_foundation", "0308_computer_merge_and_split",
                         "0315_merge_moves_source_links", "0317_close_moved_link_history"):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")

            # Two merges made before 0318: one proven only by the image agent,
            # one with a real record moved.
            wrong_survivor, wrong_absorbed = _computer(connection, "citrixapp27"), _computer(connection, "citrixappmcs")
            _record(connection, wrong_absorbed, "s1-image")
            right_survivor, right_absorbed = _computer(connection, "del-lp09"), _computer(connection, "del-lp09")
            _record(connection, right_absorbed, "s1-rename")
            ids = {}
            for label, (s, a) in {"wrong": (wrong_survivor, wrong_absorbed),
                                  "right": (right_survivor, right_absorbed)}.items():
                with connection.transaction():
                    ids[label] = connection.execute(
                        "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text)",
                        (s, a),
                    ).fetchone()[0]

            migration = importlib.import_module("apps.core.migrations.0318_roaming_agent_records")
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            yield connection, ids


def test_only_the_image_agent_is_roaming(conn):
    connection, _ids = conn
    rows = connection.execute(
        "SELECT external_id, serial_count, name_count FROM operations.identity_roaming_records"
    ).fetchall()
    assert rows == [("s1-image", 4, 4)]


def test_the_merge_proven_only_by_roaming_records_is_split(conn):
    connection, ids = conn
    states = dict(
        connection.execute(
            "SELECT id, split_at IS NOT NULL FROM operations.computer_merges WHERE id = ANY(%s)",
            ([ids["wrong"], ids["right"]],),
        ).fetchall()
    )
    assert states == {ids["wrong"]: True, ids["right"]: False}
    assert connection.execute(
        """SELECT a.actor_kind, a.reason FROM operations.computer_merges m
             JOIN operations.change_actions a ON a.id = m.split_action_id WHERE m.id = %s""",
        (ids["wrong"],),
    ).fetchone() == (
        "migration",
        "Proven only by an agent that moves between clones of one image (migration 0318).",
    )


def test_the_resolver_and_findings_queries_run_and_drop_roaming_serials(conn):
    """The statements that read the table, exactly as ingest sends them."""
    from ingest.identity import findings
    from ingest.identity.resolver import PROVEN_SPLIT_SQL

    connection, _ids = conn
    connection.execute(
        """CREATE TABLE IF NOT EXISTS operations.identity_value_rejections (
               value_kind text NOT NULL, normalized_value text NOT NULL, enabled boolean NOT NULL)"""
    )
    clone = _computer(connection, "citrixapp29")
    observation = _record(connection, clone, "s1-image")
    connection.execute(
        """UPDATE operations.entity_observation_current
              SET canonical_data = '{"serial_number": "VMW-2", "hostname": "citrixapp29"}'
            WHERE observation_id = %s""",
        (observation,),
    )
    rows = connection.execute(PROVEN_SPLIT_SQL, (1,)).fetchall()
    clone_rows = [r for r in rows if r[0] == clone]
    assert clone_rows and all(r[4] == [] for r in clone_rows)
    records = connection.execute(findings._RECORDS, (1,)).fetchall()
    serials = {r[9] for r in records if r[0] == clone}
    assert serials == {None}


def test_the_table_is_classified_and_refreshes_repeatably(conn):
    connection, _ids = conn
    assert connection.execute(
        "SELECT classification FROM operations.change_history_registry "
        "WHERE table_name = 'identity_roaming_records'"
    ).fetchone()[0] == "exempt"
    with connection.transaction():
        connection.execute("SET LOCAL ROLE ninja_ingest")
        assert connection.execute(
            "SELECT operations.refresh_identity_roaming_records(1)"
        ).fetchone()[0] == 1
