"""Migration 0325 on a real PostgreSQL: the name-collision guard (ADR-0034 section 5a).

Builds the 0322 chain (production column types, 2026-10-19) with the real
operator-decision registry and its ``validate_operator_decision`` trigger
(production definitions), then runs every statement of 0325.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA, _SchemaEditor
from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer
from apps.core.tests.test_migration_0315_postgres import LINKS
from apps.core.tests.test_migration_0318_postgres import HISTORY
from apps.core.tests.test_migration_0322_postgres import CHAIN, EXTRA, _record

CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c2")

# operations.operator_decision_dimensions and validate_operator_decision as in
# production (2026-10-19); the trigger is attached once 0322's test schema has
# created device_operator_decisions.
DECISION_REGISTRY = """
CREATE TABLE operations.operator_decision_dimensions (
    name varchar(80) PRIMARY KEY, entity_type varchar(32) NOT NULL, value_type varchar(16) NOT NULL,
    allowed_values jsonb NULL, description text NOT NULL, enabled boolean NOT NULL
);
ALTER TABLE operations.operator_decision_dimensions OWNER TO operations_migrate;
INSERT INTO operations.operator_decision_dimensions VALUES
    ('exemptions', 'device', 'json', NULL, 'Per-device exemption flags.', true),
    ('identity_excluded_records', 'device', 'json', NULL, 'Records split off.', true),
    ('identity_separate', 'device', 'json', NULL, 'Confirmed different machines.', true),
    ('in_use_confirmed', 'device', 'boolean', NULL, 'Confirmed in use.', true);
"""
DECISION_TRIGGER = r"""
CREATE FUNCTION operations.validate_operator_decision() RETURNS trigger
LANGUAGE plpgsql AS $function$
DECLARE
    dim operations.operator_decision_dimensions%ROWTYPE;
BEGIN
    SELECT * INTO dim FROM operations.operator_decision_dimensions WHERE name = NEW.dimension;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown operator decision dimension: %', NEW.dimension
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT dim.enabled THEN
        RAISE EXCEPTION 'Operator decision dimension is disabled: %', NEW.dimension
            USING ERRCODE = 'check_violation';
    END IF;
    IF dim.value_type = 'boolean' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('boolean') THEN
            RAISE EXCEPTION 'Dimension % expects JSON boolean, got %', NEW.dimension,
                jsonb_typeof(NEW.value) USING ERRCODE = 'check_violation';
        END IF;
    ELSIF dim.value_type = 'text' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('string') THEN
            RAISE EXCEPTION 'Dimension % expects JSON string, got %', NEW.dimension,
                jsonb_typeof(NEW.value) USING ERRCODE = 'check_violation';
        END IF;
    ELSIF dim.value_type = 'enum' THEN
        IF jsonb_typeof(NEW.value) NOT IN ('string') THEN
            RAISE EXCEPTION 'Dimension % expects enum (JSON string), got %', NEW.dimension,
                jsonb_typeof(NEW.value) USING ERRCODE = 'check_violation';
        END IF;
        IF dim.allowed_values IS NULL OR NOT (dim.allowed_values @> jsonb_build_array(NEW.value)) THEN
            RAISE EXCEPTION 'Dimension % value % not in allowed_values %', NEW.dimension,
                NEW.value::text, dim.allowed_values::text USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
CREATE TRIGGER trg_validate_operator_decision BEFORE INSERT OR UPDATE
    ON operations.device_operator_decisions FOR EACH ROW
    EXECUTE FUNCTION operations.validate_operator_decision();
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
            for ddl in (
                FOUNDATION_SCHEMA,
                TABLES,
                LINKS,
                HISTORY,
                EXTRA,
                FINDING_TYPES_SCHEMA,
                DECISION_REGISTRY,
                DECISION_TRIGGER,
            ):
                connection.execute(ddl)
            for name in (
                *CHAIN,
                "0322_record_names_and_shadow_naming",
                "0325_computer_name_collision_guard",
            ):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
                if hasattr(module, "register_finding_type"):
                    module.register_finding_type(None, _SchemaEditor(connection))

            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def _named(conn, name, record_name, *, client=CLIENT, lifecycle="active"):
    """A Computer named ``name`` whose reporting Ninja agent says ``record_name``."""
    device = _computer(conn, name, client)
    if lifecycle != "active":
        conn.execute(
            "UPDATE operations.devices SET lifecycle_status = %s WHERE id = %s", (lifecycle, device)
        )
    observation, _key = _record(conn, device, "Ninja", "agent.rmm", record_name, online=True)
    return device, observation


def _row(conn, device):
    return conn.execute(
        """SELECT name, name_rule, rejected_name, rejected_rule, rejected_observation_id,
                  conflicting_device_ids
             FROM operations.computer_names(1, %s)""",
        ([device],),
    ).fetchone()


def test_a_rename_into_a_live_computers_name_key_is_kept(conn):
    # The proposed name differs only in case and separators: keys collide.
    holder, _ = _named(conn, "lab220-34", "LAB220-34")
    mover, rejected = _named(conn, "ctxdesktop065", "Lab220_34")
    assert _row(conn, mover) == (
        "ctxdesktop065",
        "kept_collision",
        "lab220_34",
        "reporting_os",
        rejected,
        [holder],
    )
    # The holder is not renamed and not in collision.
    assert _row(conn, holder)[:2] == ("lab220-34", "reporting_os")


def test_pending_cleanup_counts_as_live_retired_and_other_clients_do_not(conn):
    pending, _ = _named(conn, "fs-1", "FS-1", lifecycle="pending_cleanup")
    retired, _ = _named(conn, "fs-2", "FS-2", lifecycle="retired")
    _named(conn, "fs-3", "FS-3", client=OTHER_CLIENT)
    to_pending, _ = _named(conn, "old-a", "FS-1")
    to_retired, _ = _named(conn, "old-b", "FS-2")
    to_other_client, _ = _named(conn, "old-c", "FS-3")
    assert _row(conn, to_pending)[1:2] + (_row(conn, to_pending)[5],) == (
        "kept_collision",
        [pending],
    )
    assert _row(conn, to_retired)[:2] == ("fs-2", "reporting_os")
    assert _row(conn, to_other_client)[:2] == ("fs-3", "reporting_os")
    assert retired  # the retired holder stays as it is


def test_two_renames_to_one_new_name_both_keep_their_names(conn):
    first, _ = _named(conn, "vdi-1", "NEWNAME")
    second, _ = _named(conn, "vdi-2", "NEWNAME")
    assert _row(conn, first)[:2] == ("vdi-1", "kept_collision")
    assert _row(conn, second)[:2] == ("vdi-2", "kept_collision")
    assert _row(conn, first)[5] == [second] and _row(conn, second)[5] == [first]
    # A scoped call sees the same set as the whole pass.
    whole = dict(
        (r[0], r[1])
        for r in conn.execute(
            "SELECT device_id, name_rule FROM operations.computer_names(1, NULL)"
        ).fetchall()
    )
    assert whole[first] == whole[second] == "kept_collision"


def test_confirmed_separate_machines_do_not_permit_the_rejected_name(conn):
    # "Keep separate" says the Computers are different machines, not that the
    # colliding name is right (a Hudu label on the wrong Computer).
    holder, _ = _named(conn, "kiosk", "KIOSK")
    mover, _ = _named(conn, "old-kiosk", "KIOSK")
    conn.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, gen_random_uuid(), 'identity_separate', %s::jsonb, 'two kiosks', 'op', now(), 1, %s)""",
        (json.dumps([str(holder)]), mover),
    )
    assert _row(conn, mover)[:2] == ("old-kiosk", "kept_collision")


def test_only_an_explicit_name_collision_confirmation_permits_the_name(conn):
    holder, _ = _named(conn, "scanner", "SCANNER")
    mover, _ = _named(conn, "old-scanner", "SCANNER")
    # A confirmation for another name does not apply.
    conn.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, gen_random_uuid(), 'name_collision_confirmed', '{"name": "printer"}',
                   'checked', 'op', now(), 1, %s)""",
        (mover,),
    )
    assert _row(conn, mover)[:2] == ("old-scanner", "kept_collision")
    conn.execute(
        """UPDATE operations.device_operator_decisions SET value = '{"name": "Scanner"}'
            WHERE device_id = %s AND dimension = 'name_collision_confirmed'""",
        (mover,),
    )
    assert _row(conn, mover)[:2] == ("scanner", "reporting_os")
    assert holder


def test_a_real_merge_ends_the_collision(conn):
    holder, _ = _named(conn, "nas-1", "NAS-1")
    mover, _ = _named(conn, "nas-old", "NAS-1")
    assert _row(conn, mover)[1] == "kept_collision"
    # A real merge: the absorbed Computer is no longer live.
    with conn.transaction():
        conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same machine'::text)",
            (mover, holder),
        )
    assert _row(conn, mover)[:2] == ("nas-1", "reporting_os")


def test_the_review_only_finding_type_and_policy_register_once(conn):
    assert conn.execute(
        """SELECT finding_class, display_name, issue_group, alertable, creates_device_exposure
             FROM operations.finding_types WHERE name = 'computer_name_collision'"""
    ).fetchone() == (
        "entity",
        "Name already used by another Computer",
        "Duplicate computers",
        False,
        False,
    )
    active = conn.execute(
        "SELECT version, policy FROM operations.condition_policy_versions WHERE active"
    ).fetchone()
    assert active[0] == "conditions-registry-8"
    assert "computer_name_collision" in [d["name"] for d in active[1]["definitions"]]


def test_an_operator_name_needs_an_explicit_collision_confirmation(conn):
    holder, _ = _named(conn, "front-desk", "FRONT-DESK")
    mover, _ = _named(conn, "pc-77", "PC-77")
    conn.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, gen_random_uuid(), 'name', '{"name": "Front-Desk"}', 'asked', 'op', now(), 1, %s)""",
        (mover,),
    )
    assert _row(conn, mover)[:4] == ("pc-77", "kept_collision", "front-desk", "operator")
    conn.execute(
        """UPDATE operations.device_operator_decisions
              SET value = '{"name": "Front-Desk", "collision_confirmed": true}'
            WHERE device_id = %s AND dimension = 'name'""",
        (mover,),
    )
    assert _row(conn, mover)[:2] == ("front-desk", "operator")
    assert holder


def test_collisions_are_stored_for_the_session_tenant_only(conn):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        stored = conn.execute("SELECT operations.refresh_computer_name_collisions(1)").fetchone()[0]
    rows = conn.execute(
        "SELECT count(*), bool_and(cardinality(conflicting_device_ids) > 0)"
        " FROM operations.computer_name_collisions"
    ).fetchone()
    assert stored == rows[0] and stored >= 4 and rows[1] is True
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '2', true)")
        conn.execute("SELECT operations.refresh_computer_name_collisions(1)")
    shadow = dict(
        conn.execute(
            "SELECT outcome, count(*) FROM operations.computer_name_shadow(1) GROUP BY 1"
        ).fetchall()
    )
    assert shadow.get("collision") == stored


def test_the_confirmation_dimension_is_registered_and_validated(conn):
    assert conn.execute(
        """SELECT entity_type, value_type, enabled FROM operations.operator_decision_dimensions
            WHERE name = 'name_collision_confirmed'"""
    ).fetchone() == ("device", "json", True)
    device, _ = _named(conn, "probe-dim", "PROBE-DIM")
    conn.execute(
        """INSERT INTO operations.device_operator_decisions
           VALUES (1, gen_random_uuid(), 'name_collision_confirmed', '{"name": "probe-dim"}',
                   'checked', 'op', now(), 1, %s)""",
        (device,),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """INSERT INTO operations.device_operator_decisions
               VALUES (1, gen_random_uuid(), 'name_collision_approved', '{"name": "x"}',
                       'typo', 'op', now(), 1, %s)""",
            (device,),
        )
    # The registration is recorded under its own change action.
    assert conn.execute(
        """SELECT a.action FROM operations.operator_decision_dimensions_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id
            WHERE h.entity_key = 'name_collision_confirmed'"""
    ).fetchone() == ("operator_decision_dimension.add",)
