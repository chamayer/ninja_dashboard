"""Migration 0395 on a real PostgreSQL: one-target sources settle instead of failing.

Production column definitions (2026-11-01) for the relationship tables, with the
0273 tuple trigger that rejects a second active edge of a source.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA operations;
CREATE TABLE operations.relationship_types (
    key varchar(120) PRIMARY KEY, display_name varchar(160) NOT NULL, description text NOT NULL,
    source_cardinality varchar(8) NOT NULL, target_cardinality varchar(8) NOT NULL,
    directed boolean NOT NULL, enabled boolean NOT NULL,
    source_entity_class_id varchar(80) NOT NULL, target_entity_class_id varchar(80) NOT NULL
);
INSERT INTO operations.relationship_types VALUES
    ('os_installation_runs_on_computer', 'Runs on', '', 'one', 'many', true, true,
     'os_installation', 'device');
CREATE TABLE operations.entities (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, entity_class_id varchar(80) NOT NULL
);
CREATE TABLE operations.entity_relationships (
    version integer NOT NULL, id uuid PRIMARY KEY, status varchar(16) NOT NULL,
    selection_reason varchar(40) NOT NULL, selected_authority_tier smallint,
    selected_authority_priority smallint, input_hash bytea NOT NULL,
    projected_at timestamptz NOT NULL, source_entity_id uuid NOT NULL,
    target_entity_id uuid NOT NULL, tenant_id bigint NOT NULL,
    relationship_type_id varchar(120) NOT NULL,
    UNIQUE (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
);
CREATE TABLE operations.entity_relationship_dirty (
    version integer NOT NULL DEFAULT 1, id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    queued_at timestamptz NOT NULL, reason varchar(40) NOT NULL DEFAULT 'evidence_change',
    source_entity_id uuid NOT NULL, target_entity_id uuid NOT NULL, tenant_id bigint NOT NULL,
    relationship_type_id varchar(120) NOT NULL,
    UNIQUE (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
);
CREATE TABLE operations.entity_relationship_decision_current (
    version integer NOT NULL, id uuid PRIMARY KEY, operation varchar(12) NOT NULL,
    active boolean NOT NULL, reason text NOT NULL, decided_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL, decided_by_id bigint NOT NULL,
    source_entity_id uuid NOT NULL, target_entity_id uuid NOT NULL, tenant_id bigint NOT NULL,
    relationship_type_id varchar(120) NOT NULL
);
CREATE TABLE operations.entity_relationship_evidence_current (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), resolution_status varchar(16) NOT NULL,
    authority_eligible boolean NOT NULL, authority_tier smallint NOT NULL,
    authority_priority smallint NOT NULL, active boolean NOT NULL,
    source_entity_id uuid, target_entity_id uuid, tenant_id bigint NOT NULL,
    relationship_type_id varchar(120) NOT NULL
);
CREATE TABLE operations.entity_relationship_evidence_support (
    id uuid PRIMARY KEY, evidence_id uuid NOT NULL, relationship_id uuid NOT NULL,
    tenant_id bigint NOT NULL
);
"""

TYPE = "os_installation_runs_on_computer"


def _function(module_name: str, name: str) -> str:
    sql = importlib.import_module(f"apps.core.migrations.{module_name}").FORWARD_SQL
    start = sql.index(f"CREATE OR REPLACE FUNCTION operations.{name}(")
    end = sql.index("$function$;", start) + len("$function$;")
    return sql[start:end]


@pytest.fixture()
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)
            connection.execute(
                _function("0273_repair_derived_projection_contracts", "validate_relationship_tuple")
            )
            connection.execute(
                "CREATE TRIGGER validate_relationship_current BEFORE INSERT OR UPDATE"
                " ON operations.entity_relationships FOR EACH ROW"
                " EXECUTE FUNCTION operations.validate_relationship_tuple()"
            )
            module = importlib.import_module(
                "apps.core.migrations.0395_relationship_projector_cardinality"
            )
            connection.execute(module.FORWARD_SQL)
            yield connection


def _entity(conn, entity_class):
    entity_id = uuid.uuid4()
    conn.execute("INSERT INTO operations.entities VALUES (%s, 1, %s)", (entity_id, entity_class))
    return entity_id


def _active_edge(conn, installation, computer):
    conn.execute(
        """INSERT INTO operations.entity_relationships VALUES
           (1, gen_random_uuid(), 'active', 'source_authority', 100, 100, '\\x00', now(),
            %s, %s, 1, %s)""",
        (installation, computer, TYPE),
    )


def _evidence(conn, installation, computer, *, active=True, tier=100):
    conn.execute(
        """INSERT INTO operations.entity_relationship_evidence_current
           (resolution_status, authority_eligible, authority_tier, authority_priority,
            active, source_entity_id, target_entity_id, tenant_id, relationship_type_id)
           VALUES ('resolved', true, %s, 100, %s, %s, %s, 1, %s)""",
        (tier, active, installation, computer, TYPE),
    )


def _queue(conn, installation, computer, minutes_ago):
    conn.execute(
        """INSERT INTO operations.entity_relationship_dirty
           (queued_at, source_entity_id, target_entity_id, tenant_id, relationship_type_id)
           VALUES (now() - make_interval(mins => %s), %s, %s, 1, %s)""",
        (minutes_ago, installation, computer, TYPE),
    )


def _states(conn, installation):
    rows = conn.execute(
        """SELECT target_entity_id, status, selection_reason
             FROM operations.entity_relationships WHERE source_entity_id = %s""",
        (installation,),
    ).fetchall()
    return {target: (status, reason) for target, status, reason in rows}


def test_a_moved_installation_is_demoted_before_the_new_edge_activates(conn):
    installation = _entity(conn, "os_installation")
    old, new = _entity(conn, "device"), _entity(conn, "device")
    _active_edge(conn, installation, old)
    _evidence(conn, installation, old, active=False)
    _evidence(conn, installation, new)
    # The new tuple is queued first, as in production, so it leads the batch.
    _queue(conn, installation, new, 10)
    _queue(conn, installation, old, 5)

    processed, _writes, supports = conn.execute(
        "SELECT * FROM operations.sync_entity_relationships(1)"
    ).fetchone()

    assert processed == 2
    assert supports == 1
    assert _states(conn, installation) == {
        old: ("no_evidence", "no_eligible_evidence"),
        new: ("active", "source_authority"),
    }
    assert (
        conn.execute("SELECT count(*) FROM operations.entity_relationship_dirty").fetchone()[0] == 0
    )


def test_equal_authority_disagreement_keeps_the_current_edge(conn):
    installation = _entity(conn, "os_installation")
    current, other = _entity(conn, "device"), _entity(conn, "device")
    _active_edge(conn, installation, current)
    _evidence(conn, installation, current)
    _evidence(conn, installation, other)
    _queue(conn, installation, other, 10)

    conn.execute("SELECT * FROM operations.sync_entity_relationships(10)")

    assert _states(conn, installation) == {
        current: ("active", "source_authority"),
        other: ("conflict", "targets_disagree"),
    }

    # Once the current edge loses its evidence, the other target takes the slot.
    conn.execute(
        "UPDATE operations.entity_relationship_evidence_current SET active = false"
        " WHERE target_entity_id = %s",
        (current,),
    )
    _queue(conn, installation, current, 1)
    conn.execute("SELECT * FROM operations.sync_entity_relationships(10)")

    assert _states(conn, installation) == {
        current: ("no_evidence", "no_eligible_evidence"),
        other: ("active", "source_authority"),
    }


def test_higher_authority_wins_and_new_ties_activate_nothing(conn):
    ranked = _entity(conn, "os_installation")
    strong, weak = _entity(conn, "device"), _entity(conn, "device")
    _evidence(conn, ranked, strong, tier=100)
    _evidence(conn, ranked, weak, tier=50)
    _queue(conn, ranked, weak, 10)
    _queue(conn, ranked, strong, 9)

    tied = _entity(conn, "os_installation")
    first, second = _entity(conn, "device"), _entity(conn, "device")
    _evidence(conn, tied, first)
    _evidence(conn, tied, second)
    _queue(conn, tied, first, 8)
    _queue(conn, tied, second, 7)

    conn.execute("SELECT * FROM operations.sync_entity_relationships(10)")

    assert _states(conn, ranked) == {
        strong: ("active", "source_authority"),
        weak: ("superseded", "outranked_by_other_target"),
    }
    assert _states(conn, tied) == {
        first: ("conflict", "targets_disagree"),
        second: ("conflict", "targets_disagree"),
    }
